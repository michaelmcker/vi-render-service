"""Weekly thought-leadership synthesis.

Reads everything LinkedIn (and any future source) archived to
research/thought-leadership/ during the week, runs a `claude -p` synthesis
against it, and produces a draft post in her voice as a Doc in her Drive.

Schedule: Sunday morning by default (importance.yaml budget.thought_leadership_weekly_at).
Source files move to research/thought-leadership/archive/{YYYY-Www}/ after run.

Output:
  - A Google Doc titled "Thought Leadership Draft — {week}".
  - Lives in her Drive's "Hermes — Thought Leadership" folder.
  - Telegram message with the link + a one-line preview.

If the archive is empty or the synthesis fails, Hermes pings her: "Light
week — nothing to synthesize. Want to brainstorm a topic instead?"
"""
from __future__ import annotations

import datetime as dt
import logging
import shutil
from pathlib import Path

from . import llm, notify, profiles, state
from .config import HERMES_HOME, PROMPTS_DIR
from .google import docs, drive

log = logging.getLogger("hermes.thought_leadership")

TL_DIR = HERMES_HOME / "research" / "thought-leadership"
TL_ARCHIVE_DIR = TL_DIR / "archive"
PROMPT = PROMPTS_DIR / "thought_leadership_piece.md"

DRIVE_FOLDER_NAME = "Hermes — Thought Leadership"
MAX_SOURCES_PER_RUN = 30
MAX_SOURCE_CHARS_PER_FILE = 1500


def _drive_folder_id() -> str:
    cached = state.kv_get("tl_drive_folder_id", "")
    if cached:
        return cached
    fid = drive.ensure_folder(DRIVE_FOLDER_NAME)
    state.kv_set("tl_drive_folder_id", fid)
    return fid


def _collect_sources() -> list[Path]:
    """Files that arrived this week in research/thought-leadership/ root."""
    if not TL_DIR.exists():
        return []
    files = sorted(p for p in TL_DIR.iterdir()
                   if p.is_file() and p.suffix == ".md" and not p.name.startswith("."))
    return files[:MAX_SOURCES_PER_RUN] if len(files) > MAX_SOURCES_PER_RUN else files


def _build_payload(sources: list[Path]) -> str:
    pieces = []
    for src in sources:
        text = src.read_text()
        if len(text) > MAX_SOURCE_CHARS_PER_FILE:
            text = text[:MAX_SOURCE_CHARS_PER_FILE] + "\n…[truncated]…\n"
        pieces.append(f"--- {src.name} ---\n{text}")
    return "\n\n".join(pieces)


def _archive_sources(sources: list[Path], week_label: str) -> None:
    target = TL_ARCHIVE_DIR / week_label
    target.mkdir(parents=True, exist_ok=True)
    for src in sources:
        shutil.move(str(src), str(target / src.name))
    log.info("archived %d sources to %s", len(sources), target)


def run_weekly() -> dict[str, str]:
    """Idempotent per ISO week; safe to call repeatedly on Sunday morning."""
    today = dt.date.today()
    iso_year, iso_week, _ = today.isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"
    if state.kv_get("tl_last_week", "") == week_label:
        return {"status": "skipped", "reason": "already ran this week"}

    sources = _collect_sources()
    if not sources:
        notify.send_text(
            "*Thought leadership — light week*\n\n"
            "No archived posts to synthesize this week. Want to brainstorm a "
            "topic? Reply with `/post-draft <topic>`.",
            urgent=True, kind="briefing",
        )
        state.kv_set("tl_last_week", week_label)
        return {"status": "empty"}

    voice = profiles.build_context(voice_context="default", max_chars=1500)
    payload = (
        f"VOICE CONTEXT:\n{voice}\n\n"
        f"WEEKLY THOUGHT-LEADERSHIP SOURCES (verbatim — read for patterns, "
        f"contrarian takes, what's missing):\n\n"
        f"{_build_payload(sources)}\n"
    )
    try:
        draft = llm.run(PROMPT, payload, expect_json=False, timeout=180)
    except llm.LLMError:
        log.exception("thought-leadership synthesis failed")
        notify.send_text("⚠️ Thought-leadership weekly run failed. Try `/tl-run` later.",
                         urgent=True, kind="system", audience="all")
        return {"status": "failed"}

    body = draft.strip() if isinstance(draft, str) else str(draft)
    title = f"Thought Leadership Draft — {week_label}"

    folder_id = _drive_folder_id()
    doc_id = docs.create(title, parent_folder_id=folder_id)
    docs.append_heading(doc_id, title, level=1)
    docs.append_paragraph(doc_id, "")
    docs.append_paragraph(doc_id, f"Synthesized from {len(sources)} archived posts. "
                                  f"Nikki's voice, draft only — edit before queueing.")
    docs.append_paragraph(doc_id, "")
    docs.append_heading(doc_id, "Draft", level=2)
    docs.append_markdown(doc_id, body)
    docs.append_paragraph(doc_id, "")
    docs.append_heading(doc_id, "Sources", level=2)
    for src in sources:
        docs.append_paragraph(doc_id, f"• {src.name}")

    link = drive.web_view_link(doc_id)
    notify.send_text(
        f"📝 *Thought Leadership — {week_label}*\n\n"
        f"Draft from {len(sources)} archived posts. Edit, then queue in Buffer.\n\n"
        f"{link}",
        urgent=True, kind="briefing",
        keyboard=[[{"text": "📄 Open Doc", "url": link}]],
    )

    _archive_sources(sources, week_label)
    state.kv_set("tl_last_week", week_label)
    return {"status": "ok", "doc_id": doc_id, "link": link, "week": week_label}
