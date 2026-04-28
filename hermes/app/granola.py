"""Granola — STUB. Tail her local notes directory for new transcripts.

Granola stores meeting notes as files under
    ~/Library/Application Support/Granola/  (path may vary by version)

GRANOLA_NOTES_DIR in .env points at the directory. Hermes watches mtime,
parses the latest transcripts, and queues a "follow-up draft" task.

Planned surface:
    list_recent(since_unix: int) -> list[Note]
    parse(note_path: Path) -> ParsedTranscript
        # title, attendees (best-effort), datetime, raw transcript text
    queue_followup(parsed: ParsedTranscript) -> None
        # drafts a recap + suggested next-step email per external attendee

Design notes:
- File format may be JSON, markdown, or sqlite depending on Granola version.
  Run `ls -la <GRANOLA_NOTES_DIR>` on the Mac during install to confirm and
  pick the right parser. Until then, this module is intentionally empty.
- Throttle: process at most 5 transcripts per pass. Long meetings produce
  long transcripts; we'll truncate to ~6k tokens before LLM passes.
"""
