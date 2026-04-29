"""Profiles store: structured (SQLite) + narrative (markdown) memory.

Hermes accumulates context on every person, account, spreadsheet recipe,
and voice sample over time. This module is the single API for that store.

Storage layout:
  state.sqlite tables:
    - people, accounts, spreadsheet_recipes, voice_samples, network
  filesystem:
    - profiles/people/<email-slug>.md
    - profiles/accounts/<domain-slug>.md
    - profiles/spreadsheets/<sheet_id>.md
    - profiles/voice/<context>.md
    - brand/{icp,product,pricing,network}.md  (mostly-static)

Hot path:
  - Gmail watcher / Slack triage call note_interaction(person, account, summary)
    after every classified message.
  - Draft approval hook calls capture_voice_sample(context, body) so future
    drafts have ground-truth examples.
  - Slash commands and prompt builders call build_context(...) to assemble
    the relevant snippets into a prompt prefix.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import state
from .config import HERMES_HOME

log = logging.getLogger("hermes.profiles")

PROFILES_DIR = HERMES_HOME / "profiles"
BRAND_DIR = HERMES_HOME / "brand"


# ───────────────────────── schema ─────────────────────────

PROFILES_SCHEMA = """
CREATE TABLE IF NOT EXISTS people (
    email             TEXT PRIMARY KEY,
    display_name      TEXT,
    title             TEXT,
    company_slug      TEXT,
    last_interaction  INTEGER,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    voice_context     TEXT,
    is_vip            INTEGER NOT NULL DEFAULT 0,
    is_off_limits     INTEGER NOT NULL DEFAULT 0,
    no_draft          INTEGER NOT NULL DEFAULT 0,
    notes_path        TEXT,
    updated_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    slug              TEXT PRIMARY KEY,
    name              TEXT,
    domain            TEXT,
    industry          TEXT,
    sfdc_account_id   TEXT,
    is_named_account  INTEGER NOT NULL DEFAULT 0,
    last_touch        INTEGER,
    notes_path        TEXT,
    updated_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS spreadsheet_recipes (
    spreadsheet_id    TEXT PRIMARY KEY,
    title             TEXT,
    instructions_path TEXT,
    last_run          INTEGER,
    last_outcome      TEXT,
    updated_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS voice_samples (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    context           TEXT NOT NULL,         -- 'customer','internal','intro','board','default'
    recipient_email   TEXT,
    body              TEXT NOT NULL,
    captured_at       INTEGER NOT NULL,
    source            TEXT NOT NULL          -- 'imported','approved-draft','sent-mail-mirror'
);

CREATE TABLE IF NOT EXISTS network (
    person_email      TEXT PRIMARY KEY,
    relationship      TEXT,                  -- 'mentor','champion','investor','coworker'
    notes             TEXT,
    intro_count       INTEGER NOT NULL DEFAULT 0,
    updated_at        INTEGER NOT NULL,
    FOREIGN KEY (person_email) REFERENCES people(email)
);
"""


def _ensure_schema() -> None:
    with state.conn() as c:
        c.executescript(PROFILES_SCHEMA)


# ───────────────────────── slugs / paths ─────────────────────────

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def email_slug(email: str) -> str:
    return _SLUG_RE.sub("-", email.strip().lower()).strip("-")


def domain_slug(domain: str) -> str:
    return _SLUG_RE.sub("-", domain.strip().lower()).strip("-")


def person_notes_path(email: str) -> Path:
    return PROFILES_DIR / "people" / f"{email_slug(email)}.md"


def account_notes_path(slug: str) -> Path:
    return PROFILES_DIR / "accounts" / f"{slug}.md"


def spreadsheet_notes_path(sheet_id: str) -> Path:
    return PROFILES_DIR / "spreadsheets" / f"{sheet_id}.md"


def voice_notes_path(context: str) -> Path:
    return PROFILES_DIR / "voice" / f"{context}.md"


def domain_from_email(email: str) -> str:
    return email.split("@")[-1].lower() if "@" in email else ""


# ───────────────────────── people ─────────────────────────

@dataclass
class Person:
    email: str
    display_name: str = ""
    title: str = ""
    company_slug: str = ""
    last_interaction: int = 0
    interaction_count: int = 0
    voice_context: str = ""
    is_vip: bool = False
    is_off_limits: bool = False
    no_draft: bool = False
    notes_path: str = ""


def get_person(email: str) -> Person | None:
    _ensure_schema()
    with state.conn() as c:
        r = c.execute("SELECT * FROM people WHERE email=?", (email.lower(),)).fetchone()
    if not r:
        return None
    return Person(
        email=r["email"], display_name=r["display_name"] or "", title=r["title"] or "",
        company_slug=r["company_slug"] or "", last_interaction=r["last_interaction"] or 0,
        interaction_count=r["interaction_count"], voice_context=r["voice_context"] or "",
        is_vip=bool(r["is_vip"]), is_off_limits=bool(r["is_off_limits"]),
        no_draft=bool(r["no_draft"]), notes_path=r["notes_path"] or "",
    )


def upsert_person(email: str, **fields: Any) -> Person:
    """Create or update a person row. Unknown fields are ignored."""
    _ensure_schema()
    email = email.lower()
    existing = get_person(email)
    now = int(time.time())
    notes = person_notes_path(email)
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.exists():
        notes.write_text(f"# {email}\n\n_(No notes yet — Hermes will append as it observes.)_\n")
    if existing:
        merged = {**existing.__dict__, **{k: v for k, v in fields.items() if v is not None}}
    else:
        merged = {"email": email, **{k: v for k, v in fields.items() if v is not None}}
    cols = ("email", "display_name", "title", "company_slug", "last_interaction",
            "interaction_count", "voice_context", "is_vip", "is_off_limits",
            "no_draft", "notes_path", "updated_at")
    vals = (
        merged.get("email", email),
        merged.get("display_name", ""), merged.get("title", ""),
        merged.get("company_slug", ""), merged.get("last_interaction", 0),
        merged.get("interaction_count", 0), merged.get("voice_context", ""),
        int(bool(merged.get("is_vip", False))), int(bool(merged.get("is_off_limits", False))),
        int(bool(merged.get("no_draft", False))), str(notes),
        now,
    )
    with state.conn() as c:
        c.execute(
            f"INSERT OR REPLACE INTO people ({','.join(cols)}) "
            f"VALUES ({','.join(['?'] * len(cols))})",
            vals,
        )
    return get_person(email)  # type: ignore[return-value]


def append_person_note(email: str, note: str) -> None:
    """Append a one-line note to the person's markdown file with timestamp."""
    notes = person_notes_path(email)
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.exists():
        notes.write_text(f"# {email}\n\n")
    line = f"- _{dt.datetime.now().date().isoformat()}_ — {note.strip()}\n"
    with notes.open("a") as f:
        f.write(line)


def note_interaction(*, email: str, display_name: str = "", summary: str = "",
                     voice_context: str = "") -> Person:
    """Hot-path: called after every classified message. Bumps counters + appends note."""
    p = get_person(email)
    count = (p.interaction_count if p else 0) + 1
    person = upsert_person(
        email,
        display_name=display_name or (p.display_name if p else ""),
        company_slug=domain_slug(domain_from_email(email)),
        last_interaction=int(time.time()),
        interaction_count=count,
        voice_context=voice_context or (p.voice_context if p else ""),
    )
    if summary:
        append_person_note(email, summary[:200])
    return person


# ───────────────────────── accounts ─────────────────────────

@dataclass
class Account:
    slug: str
    name: str = ""
    domain: str = ""
    industry: str = ""
    sfdc_account_id: str = ""
    is_named_account: bool = False
    last_touch: int = 0
    notes_path: str = ""


def get_account(slug: str) -> Account | None:
    _ensure_schema()
    with state.conn() as c:
        r = c.execute("SELECT * FROM accounts WHERE slug=?", (slug,)).fetchone()
    if not r:
        return None
    return Account(
        slug=r["slug"], name=r["name"] or "", domain=r["domain"] or "",
        industry=r["industry"] or "", sfdc_account_id=r["sfdc_account_id"] or "",
        is_named_account=bool(r["is_named_account"]), last_touch=r["last_touch"] or 0,
        notes_path=r["notes_path"] or "",
    )


def upsert_account(slug: str, **fields: Any) -> Account:
    _ensure_schema()
    now = int(time.time())
    existing = get_account(slug)
    notes = account_notes_path(slug)
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.exists():
        notes.write_text(f"# {fields.get('name', slug)}\n\n_(No notes yet.)_\n")
    merged = {**(existing.__dict__ if existing else {"slug": slug}),
              **{k: v for k, v in fields.items() if v is not None}}
    cols = ("slug", "name", "domain", "industry", "sfdc_account_id",
            "is_named_account", "last_touch", "notes_path", "updated_at")
    vals = (
        merged.get("slug", slug), merged.get("name", ""), merged.get("domain", ""),
        merged.get("industry", ""), merged.get("sfdc_account_id", ""),
        int(bool(merged.get("is_named_account", False))),
        merged.get("last_touch", 0), str(notes), now,
    )
    with state.conn() as c:
        c.execute(
            f"INSERT OR REPLACE INTO accounts ({','.join(cols)}) "
            f"VALUES ({','.join(['?'] * len(cols))})",
            vals,
        )
    return get_account(slug)  # type: ignore[return-value]


def append_account_note(slug: str, note: str) -> None:
    notes = account_notes_path(slug)
    notes.parent.mkdir(parents=True, exist_ok=True)
    if not notes.exists():
        notes.write_text(f"# {slug}\n\n")
    line = f"- _{dt.datetime.now().date().isoformat()}_ — {note.strip()}\n"
    with notes.open("a") as f:
        f.write(line)


# ───────────────────────── spreadsheet recipes ─────────────────────────

def get_recipe(spreadsheet_id: str) -> dict[str, Any] | None:
    """Returns the recipe dict (with `instructions` text loaded) or None."""
    _ensure_schema()
    with state.conn() as c:
        r = c.execute("SELECT * FROM spreadsheet_recipes WHERE spreadsheet_id=?",
                      (spreadsheet_id,)).fetchone()
    if not r:
        return None
    out = dict(r)
    p = Path(out.get("instructions_path") or "")
    out["instructions"] = p.read_text() if p.exists() else ""
    return out


def save_recipe(spreadsheet_id: str, *, title: str, instructions: str,
                last_outcome: str = "") -> None:
    _ensure_schema()
    notes = spreadsheet_notes_path(spreadsheet_id)
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(instructions)
    now = int(time.time())
    with state.conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO spreadsheet_recipes "
            "(spreadsheet_id, title, instructions_path, last_run, last_outcome, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (spreadsheet_id, title, str(notes), now, last_outcome, now),
        )


# ───────────────────────── voice samples ─────────────────────────

VOICE_CONTEXTS = ("customer", "internal", "intro", "board", "default")

# Heuristics for picking a voice context from a recipient email.
# Tunable via importance.yaml `voice.context_rules` later.
INTERNAL_DOMAINS = ("verticalimpression.com",)


def infer_voice_context(email: str) -> str:
    """Heuristic mapping of recipient email -> voice context.

    Order of precedence:
      1. Person record's voice_context (manual override)
      2. Internal domain match
      3. is_vip + a 'board'/'investor' tag (future, not yet plumbed)
      4. Known account in `accounts` table -> 'customer'
      5. fallback: 'default'
    """
    if not email or "@" not in email:
        return "default"
    p = get_person(email)
    if p and p.voice_context:
        return p.voice_context
    domain = domain_from_email(email)
    if any(domain == d or domain.endswith("." + d) for d in INTERNAL_DOMAINS):
        return "internal"
    if get_account(domain_slug(domain)):
        return "customer"
    return "default"


def capture_voice_sample(*, context: str, body: str, recipient_email: str = "",
                         source: str = "approved-draft") -> int:
    _ensure_schema()
    if context not in VOICE_CONTEXTS:
        context = "default"
    with state.conn() as c:
        cur = c.execute(
            "INSERT INTO voice_samples (context, recipient_email, body, captured_at, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (context, recipient_email.lower(), body.strip(), int(time.time()), source),
        )
        return cur.lastrowid


def voice_samples_for(context: str, *, limit: int = 5) -> list[str]:
    """Most-recent N samples for a context, falling back to default if empty."""
    _ensure_schema()
    with state.conn() as c:
        rows = c.execute(
            "SELECT body FROM voice_samples WHERE context=? ORDER BY captured_at DESC LIMIT ?",
            (context, limit),
        ).fetchall()
    if rows:
        return [r["body"] for r in rows]
    if context != "default":
        return voice_samples_for("default", limit=limit)
    return []


# ───────────────────────── prompt context builder ─────────────────────────

def build_context(*, recipient_email: str = "", account_slug: str = "",
                  voice_context: str = "default", touches_money: bool = False,
                  max_chars: int = 3500) -> str:
    """Assemble a CONTEXT block for prompts that act on a specific person/account.

    Returned string is markdown, ready to inject ahead of the model's instruction.
    Truncates to max_chars, oldest sections dropped first.
    """
    parts: list[str] = []

    if recipient_email:
        p = get_person(recipient_email)
        notes_p = person_notes_path(recipient_email)
        if p:
            parts.append(
                f"### Recipient: {p.display_name or recipient_email}\n"
                f"- email: {p.email}\n"
                f"- title: {p.title or '(unknown)'}\n"
                f"- company: {p.company_slug or domain_from_email(recipient_email)}\n"
                f"- last contact: {_fmt_ts(p.last_interaction)}\n"
                f"- interactions: {p.interaction_count}\n"
                f"- VIP: {'yes' if p.is_vip else 'no'}\n"
                f"- voice context: {p.voice_context or '(unset)'}\n"
            )
        if notes_p.exists():
            parts.append(f"#### Notes on this person\n{notes_p.read_text().strip()}\n")

    if account_slug:
        a = get_account(account_slug)
        notes_a = account_notes_path(account_slug)
        if a:
            parts.append(
                f"### Account: {a.name or account_slug}\n"
                f"- domain: {a.domain}\n"
                f"- industry: {a.industry or '(unknown)'}\n"
                f"- last touch: {_fmt_ts(a.last_touch)}\n"
                f"- named account: {'yes' if a.is_named_account else 'no'}\n"
            )
        if notes_a.exists():
            parts.append(f"#### Notes on this account\n{notes_a.read_text().strip()}\n")

    voice_md = voice_notes_path(voice_context)
    if voice_md.exists():
        parts.append(f"### Voice — {voice_context}\n{voice_md.read_text().strip()}\n")
    samples = voice_samples_for(voice_context, limit=3)
    if samples:
        rendered = "\n\n---\n\n".join(samples)
        parts.append(f"### Recent voice samples\n{rendered}\n")

    if touches_money:
        pricing = BRAND_DIR / "pricing.md"
        if pricing.exists():
            parts.append(f"### Pricing guardrails (binding)\n{pricing.read_text().strip()}\n")

    icp = BRAND_DIR / "icp.md"
    if icp.exists() and account_slug:
        parts.append(f"### ICP\n{icp.read_text().strip()}\n")

    blob = "\n".join(parts).strip()
    if len(blob) > max_chars:
        blob = blob[-max_chars:]
        # Snap to the next heading so we don't cut mid-section.
        if "\n### " in blob:
            blob = blob[blob.index("\n### ") + 1:]
    return blob


def _fmt_ts(ts: int) -> str:
    if not ts:
        return "(never)"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


# ───────────────────────── flag helpers (used by /vip etc.) ─────────────────────────

def set_vip(email: str, vip: bool = True) -> None:
    upsert_person(email, is_vip=vip)


def set_off_limits(email: str, off: bool = True) -> None:
    upsert_person(email, is_off_limits=off, no_draft=off)


def set_no_draft(email: str, no_draft: bool = True) -> None:
    upsert_person(email, no_draft=no_draft)


def all_vips() -> list[str]:
    _ensure_schema()
    with state.conn() as c:
        rows = c.execute("SELECT email FROM people WHERE is_vip=1").fetchall()
    return [r["email"] for r in rows]


def all_off_limits() -> Iterable[str]:
    _ensure_schema()
    with state.conn() as c:
        rows = c.execute("SELECT email FROM people WHERE is_off_limits=1").fetchall()
    return [r["email"] for r in rows]
