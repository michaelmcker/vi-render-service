"""Hero skill: pre-call prep brief.

Triggered manually (Telegram `/prep` or Claude Code `/pre-call-prep` slash
command). Output: a Google Doc in her "Hermes — Call Prep" folder, plus a
Telegram link.

Pipeline:
  1. Resolve target meeting:
       - No arg: next non-internal calendar event in the next 24h
       - "in N min": next event ≥ now+N min
       - text snippet: substring match against today's events
  2. Pull external attendees (anyone not on her email's domain).
  3. For each external attendee:
       - profiles.get_person notes
       - Search Gmail for last 1-3 messages with that address (read-only).
  4. Account context: profiles.get_account by sender's domain.
  5. Run claude -p with prompts/pre_call_prep.md.
  6. Create Doc in "Hermes — Call Prep" folder, append the markdown.
  7. Telegram link.

Apollo / SFDC enrichment: stubbed for v2 (the modules are stubs). When
they're wired up, prepend their context to the ATTENDEE PROFILES block.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import llm, profiles, state
from .config import PROMPTS_DIR
from .google import calendar as gcal, docs, drive, gmail

log = logging.getLogger("hermes.pre_call_prep")

PROMPT = PROMPTS_DIR / "pre_call_prep.md"
DRIVE_FOLDER_NAME = "Hermes — Call Prep"


def _drive_folder_id() -> str:
    cached = state.kv_get("prep_drive_folder_id", "")
    if cached:
        return cached
    fid = drive.ensure_folder(DRIVE_FOLDER_NAME)
    state.kv_set("prep_drive_folder_id", fid)
    return fid


def _self_domain() -> str:
    """Best-effort: from the latest email she's a recipient on, or fallback."""
    cached = state.kv_get("self_email_domain", "")
    if cached:
        return cached
    # No good way to learn this without an email; conservative fallback.
    return "verticalimpression.com"


def _resolve_meeting(arg: str = "") -> dict[str, Any] | None:
    upcoming = gcal.upcoming(hours=48)
    if not upcoming:
        return None
    if not arg.strip():
        # Next non-self-only event.
        for ev in upcoming:
            if ev["attendees"] and ev["is_external"]:
                return ev
        return upcoming[0]
    arg = arg.strip().lower()
    if arg.startswith("in "):
        try:
            mins = int(arg.split()[1])
        except (ValueError, IndexError):
            mins = 0
        threshold = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=mins)
        for ev in upcoming:
            try:
                start = dt.datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if start >= threshold:
                return ev
        return None
    # Substring match
    for ev in upcoming:
        if arg in (ev.get("summary") or "").lower():
            return ev
    return None


def _last_thread_with(email: str, *, max_messages: int = 3) -> list[dict[str, Any]]:
    """Read-only Gmail search for the last few exchanges with this address."""
    try:
        from googleapiclient.discovery import build
        from .google._safety import safe_authorized_http
        g = build("gmail", "v1", http=safe_authorized_http(), cache_discovery=False)
        res = g.users().messages().list(
            userId="me", q=f"from:{email} OR to:{email}",
            maxResults=max_messages,
        ).execute()
        return [gmail.get_message(m["id"]) for m in res.get("messages", [])]
    except Exception:
        log.exception("gmail thread lookup failed for %s", email)
        return []


def _build_attendee_section(attendees: list[str], self_domain: str) -> str:
    """Markdown bullets per external attendee with whatever profile data we have."""
    out: list[str] = []
    for email in attendees:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        if domain == self_domain:
            continue
        person = profiles.get_person(email)
        notes_path = profiles.person_notes_path(email)
        notes_blob = notes_path.read_text() if notes_path.exists() else ""
        thread = _last_thread_with(email, max_messages=2)
        thread_excerpts = "\n".join(
            f"  - [{m.get('subject','')}] {(m.get('snippet','') or '')[:160]}"
            for m in thread
        )
        out.append(
            f"### {email}\n"
            f"- title: {(person.title if person else '') or '(unknown)'}\n"
            f"- last contact: {profiles._fmt_ts(person.last_interaction) if person else '(never)'}\n"
            f"- interactions: {person.interaction_count if person else 0}\n"
            f"- VIP: {'yes' if person and person.is_vip else 'no'}\n"
            + (f"- accumulated notes:\n{notes_blob.strip()}\n" if notes_blob.strip() else "")
            + (f"- recent threads:\n{thread_excerpts}\n" if thread_excerpts else "")
        )
    return "\n".join(out) if out else "(no external attendees with profile data)"


def run(arg: str = "") -> dict[str, str]:
    """Returns {status, doc_link} or {status, reason}."""
    meeting = _resolve_meeting(arg)
    if not meeting:
        return {"status": "no_meeting",
                "reason": "no calendar event found in the next 48h"}

    self_domain = _self_domain()
    external = [a for a in meeting.get("attendees", [])
                if "@" in a and a.split("@")[-1].lower() != self_domain]

    # Account context: domain of the most-common external attendee.
    account_slug = ""
    if external:
        primary_domain = external[0].split("@")[-1].lower()
        account_slug = profiles.domain_slug(primary_domain)

    voice = profiles.build_context(voice_context="default", max_chars=1500)
    account_blob = ""
    if account_slug:
        a = profiles.get_account(account_slug)
        notes_a = profiles.account_notes_path(account_slug)
        if notes_a.exists():
            account_blob = notes_a.read_text().strip()
        elif a:
            account_blob = f"Domain: {a.domain}; named_account: {a.is_named_account}"
    attendee_blob = _build_attendee_section(external, self_domain)

    payload = (
        f"VOICE:\n{voice}\n\n"
        f"MEETING:\n"
        f"  title: {meeting.get('summary', '')}\n"
        f"  start: {meeting.get('start', '')}\n"
        f"  end: {meeting.get('end', '')}\n"
        f"  attendees: {', '.join(meeting.get('attendees', []))}\n"
        f"  conference: {meeting.get('conference_url', '')}\n\n"
        f"ATTENDEE PROFILES:\n{attendee_blob}\n\n"
        f"ACCOUNT PROFILE:\n{account_blob or '(none)'}\n"
    )
    try:
        markdown = llm.run(PROMPT, payload, expect_json=False, timeout=120)
    except llm.LLMError:
        log.exception("pre-call-prep generation failed")
        return {"status": "failed", "reason": "claude -p failed"}

    body = markdown.strip() if isinstance(markdown, str) else str(markdown)

    # Persist to Drive.
    folder_id = _drive_folder_id()
    title = f"Prep — {meeting.get('summary', 'Meeting')} — {meeting.get('start', '')[:16]}"
    doc_id = docs.create(title, parent_folder_id=folder_id)
    docs.append_heading(doc_id, title, level=1)
    docs.append_paragraph(doc_id, "")
    docs.append_markdown(doc_id, body)

    link = drive.web_view_link(doc_id)
    return {"status": "ok", "doc_link": link, "title": title}
