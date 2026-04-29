"""Granola API client.

Granola produces a transcript + AI summary for every meeting Nikki records.
Hermes polls the API periodically, archives each new note, identifies the
account from attendee email domains, appends to the account's profile, and
pings Telegram with a `/follow-up <id>` button so she can request a draft.

ENDPOINT NOTES
==============
The exact endpoint paths and auth scheme are easy to misremember from
training data; this client pulls them from environment variables and uses
documented placeholders. Verify these against Granola's actual API docs
on first install:

    GRANOLA_API_BASE      e.g. https://api.granola.ai/v1
    GRANOLA_API_KEY       Bearer token from her Granola account
    GRANOLA_LIST_PATH     default: /notes        (override if their path differs)
    GRANOLA_NOTE_PATH     default: /notes/{id}

The client is built so swapping endpoints is one env-var change — no code
edit needed if the URL pattern is REST-conventional.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from . import notify, profiles, state
from .config import HERMES_HOME

log = logging.getLogger("hermes.granola")

GRANOLA_DIR = HERMES_HOME / "research" / "granola"

DEFAULT_BASE = "https://api.granola.ai/v1"
DEFAULT_LIST_PATH = "/notes"
DEFAULT_NOTE_PATH = "/notes/{id}"


def _config() -> dict[str, str]:
    return {
        "base": os.environ.get("GRANOLA_API_BASE", DEFAULT_BASE).rstrip("/"),
        "key": os.environ.get("GRANOLA_API_KEY", ""),
        "list_path": os.environ.get("GRANOLA_LIST_PATH", DEFAULT_LIST_PATH),
        "note_path": os.environ.get("GRANOLA_NOTE_PATH", DEFAULT_NOTE_PATH),
    }


def _headers(cfg: dict[str, str]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg['key']}",
        "Accept": "application/json",
    }


# ──────────────────────── API calls ────────────────────────

def list_notes_since(since_unix: int) -> list[dict[str, Any]]:
    """Returns notes updated after `since_unix`, oldest first.

    The shape Hermes expects per item (after _normalize):
        id, title, started_at (unix), ended_at (unix), attendees [emails],
        summary (str), transcript_excerpt (str). Missing fields default empty.
    """
    cfg = _config()
    if not cfg["key"]:
        log.warning("GRANOLA_API_KEY not set; skipping poll")
        return []
    url = cfg["base"] + cfg["list_path"]
    params = {
        # Conventional REST patterns. If their docs use different param names,
        # swap here.
        "updated_after": dt.datetime.fromtimestamp(since_unix, dt.timezone.utc).isoformat(),
        "limit": 50,
    }
    try:
        r = httpx.get(url, headers=_headers(cfg), params=params, timeout=20)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("granola list failed: %s", e)
        return []

    body = r.json()
    items = body if isinstance(body, list) else body.get("data") or body.get("notes") or []
    return [_normalize(n) for n in items]


def get_note(note_id: str) -> dict[str, Any] | None:
    """Fetch a single note with its full transcript."""
    cfg = _config()
    if not cfg["key"]:
        return None
    url = cfg["base"] + cfg["note_path"].format(id=note_id)
    try:
        r = httpx.get(url, headers=_headers(cfg), timeout=30)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("granola get_note(%s) failed: %s", note_id, e)
        return None
    body = r.json()
    note = body.get("data") if isinstance(body, dict) and "data" in body else body
    return _normalize(note, with_full_transcript=True)


# ──────────────────────── normalize ────────────────────────

def _normalize(raw: dict[str, Any], *, with_full_transcript: bool = False) -> dict[str, Any]:
    """Coerce whatever Granola returns into the shape Hermes uses internally.

    Defends against name variants (`title` vs `name`, `attendees` vs
    `participants`, etc.) so endpoint changes don't ripple through the codebase.
    """
    def _first(*keys, default=""):
        for k in keys:
            v = raw.get(k)
            if v:
                return v
        return default

    started = _ts(_first("started_at", "start_time", "start", "scheduled_at"))
    ended = _ts(_first("ended_at", "end_time", "end"))
    attendees_raw = raw.get("attendees") or raw.get("participants") or raw.get("invitees") or []
    attendees: list[str] = []
    for a in attendees_raw:
        if isinstance(a, str):
            attendees.append(a.lower())
        elif isinstance(a, dict):
            email = a.get("email") or a.get("address") or ""
            if email:
                attendees.append(email.lower())

    transcript_full = ""
    if with_full_transcript:
        transcript_full = _first("transcript", "transcript_text", "raw_transcript",
                                 "full_transcript", default="")

    return {
        "id": str(_first("id", "note_id", "uuid")),
        "title": _first("title", "name", "subject", default="(untitled)"),
        "started_at": started,
        "ended_at": ended,
        "attendees": attendees,
        "summary": _first("summary", "ai_summary", "notes", default=""),
        "transcript_excerpt": (transcript_full or _first("transcript_excerpt", "preview", default=""))[:1500],
        "transcript_full": transcript_full,
        "url": _first("url", "web_url", "view_url", default=""),
    }


def _ts(val: Any) -> int:
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val:
        try:
            return int(dt.datetime.fromisoformat(val.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return 0


# ──────────────────────── archive + profile updates ────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", s)[:80].strip("-").lower() or "untitled"


def archive_note(note: dict[str, Any]) -> Path:
    """Save the (excerpt-or-full) transcript verbatim under research/granola/."""
    GRANOLA_DIR.mkdir(parents=True, exist_ok=True)
    date = dt.date.fromtimestamp(note["started_at"] or 0).isoformat() if note["started_at"] else "undated"
    path = GRANOLA_DIR / f"{date}-{_slug(note['title'])}-{note['id']}.md"
    body = (
        f"# {note['title']}\n\n"
        f"**Started**: {dt.datetime.fromtimestamp(note['started_at']).isoformat() if note['started_at'] else '(unknown)'}\n"
        f"**Attendees**: {', '.join(note['attendees']) or '(none)'}\n"
        f"**Granola URL**: {note.get('url', '')}\n\n"
        f"## Summary\n\n{note.get('summary') or '(no summary)'}\n\n"
        f"## Transcript\n\n{note.get('transcript_full') or note.get('transcript_excerpt') or '(no transcript)'}\n"
    )
    path.write_text(body)
    return path


def update_account_from_note(note: dict[str, Any]) -> str:
    """Pick the most-likely external account from attendees and append a
    one-liner to its profile. Returns the account slug (or '' if none)."""
    self_domain = state.kv_get("self_email_domain", "verticalimpression.com")
    external = [e for e in note["attendees"]
                if "@" in e and e.split("@")[-1] != self_domain]
    if not external:
        return ""
    # Take the most-common external domain.
    from collections import Counter
    primary_domain = Counter(e.split("@")[-1] for e in external).most_common(1)[0][0]
    slug = profiles.domain_slug(primary_domain)
    profiles.upsert_account(slug, domain=primary_domain,
                            last_touch=note["started_at"] or 0)
    summary = note.get("summary", "") or note.get("title", "")
    profiles.append_account_note(slug, f"meeting: {summary[:160]}")
    return slug


# ──────────────────────── poll loop (called from daemon) ────────────────────────

def poll_once() -> dict[str, int]:
    """Pulls notes since last_check; archives + profile-updates + telegram-pings.

    Counts: {fetched, new, archived}.
    """
    counts = {"fetched": 0, "new": 0, "archived": 0}
    last_check = int(state.kv_get("granola_last_check", "0") or "0")
    if not last_check:
        last_check = int((dt.datetime.now() - dt.timedelta(days=2)).timestamp())

    notes = list_notes_since(last_check)
    counts["fetched"] = len(notes)

    for n in notes:
        if not n["id"]:
            continue
        ext_id = f"granola:{n['id']}"
        if state.already_seen("granola", ext_id):
            continue
        # Pull full transcript for archiving + downstream /follow-up.
        full = get_note(n["id"]) or n
        archive_note(full)
        counts["archived"] += 1
        update_account_from_note(full)
        state.mark_seen("granola", ext_id, "today",
                        full.get("title", "")[:120],
                        triage={"granola_id": full["id"], "title": full["title"],
                                "attendees": full["attendees"]})
        counts["new"] += 1
        _ping_new_note(full)

    state.kv_set("granola_last_check", str(int(dt.datetime.now().timestamp())))
    return counts


def _ping_new_note(note: dict[str, Any]) -> None:
    title = note.get("title", "(untitled)")
    summary = (note.get("summary") or "")[:240]
    attendees = ", ".join(note["attendees"][:3])
    if len(note["attendees"]) > 3:
        attendees += f" +{len(note['attendees']) - 3}"
    text = (
        f"📝 *New Granola transcript*\n"
        f"_{title}_\n"
        f"with {attendees or '(no attendees)'}\n\n"
        f"{summary}"
    )
    keyboard = [[
        {"text": "📨 Draft follow-up", "callback_data": f"granola_followup:{note['id']}"},
        {"text": "📋 Win/loss recap", "callback_data": f"granola_winloss:{note['id']}"},
    ]]
    notify.send_text(text, kind="today", keyboard=keyboard, audience="primary")
