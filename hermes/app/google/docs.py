"""Docs — read + write.

Used for research briefs, account plans, win/loss recaps. Hermes can create
new Docs and append to ones it created. To touch a pre-existing Doc Nikki made,
she pastes its ID into a slash command — we don't auto-discover.

Surface (v1):
    create(title, *, parent_folder_id=None) -> doc_id
    read_text(doc_id) -> str
    append_paragraph(doc_id, text) -> None
    append_heading(doc_id, text, *, level=2) -> None
    append_markdown(doc_id, md) -> None    # minimal: paragraphs + headings + bold/italic
"""
from __future__ import annotations

import logging
import re
from typing import Any

from googleapiclient.discovery import build

from ._safety import safe_authorized_http

log = logging.getLogger("hermes.docs")


def _client():
    return build("docs", "v1", http=safe_authorized_http(), cache_discovery=False)


def _drive_client():
    # Docs API can't set a parent folder at create time; Drive can.
    return build("drive", "v3", http=safe_authorized_http(), cache_discovery=False)


def create(title: str, *, parent_folder_id: str | None = None) -> str:
    """Create a Doc. Returns its document id."""
    doc = _client().documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]
    if parent_folder_id:
        _drive_client().files().update(
            fileId=doc_id,
            addParents=parent_folder_id,
            removeParents="root",
            fields="id, parents",
        ).execute()
    log.info("created Doc %s (%s)", doc_id, title)
    return doc_id


def read_text(doc_id: str) -> str:
    """Plain-text export of the Doc. Headings preserved as text."""
    doc = _client().documents().get(documentId=doc_id).execute()
    out: list[str] = []
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        line = "".join(
            r.get("textRun", {}).get("content", "")
            for r in para.get("elements", [])
        )
        out.append(line)
    return "".join(out)


def append_paragraph(doc_id: str, text: str) -> None:
    _batch_update(doc_id, [{"insertText": {"endOfSegmentLocation": {}, "text": text + "\n"}}])


def append_heading(doc_id: str, text: str, *, level: int = 2) -> None:
    requests = [
        {"insertText": {"endOfSegmentLocation": {}, "text": text + "\n"}},
    ]
    # Style the just-inserted text as a heading.
    # We insert at end-of-doc, so we need the doc length to know the range.
    end = _doc_end_index(doc_id)
    start = end  # before insert
    new_end = end + len(text) + 1
    requests.append({
        "updateParagraphStyle": {
            "range": {"startIndex": start, "endIndex": new_end},
            "paragraphStyle": {"namedStyleType": f"HEADING_{level}"},
            "fields": "namedStyleType",
        }
    })
    _batch_update(doc_id, requests)


def append_markdown(doc_id: str, md: str) -> None:
    """Minimal markdown: # / ## / ### headings, plain paragraphs.

    No inline bold/italic/lists in v1 — keep simple. Slash commands that need
    rich formatting can build batchUpdate requests directly.
    """
    for raw_line in md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            append_paragraph(doc_id, "")
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            append_heading(doc_id, m.group(2), level=level)
        else:
            append_paragraph(doc_id, line)


def _doc_end_index(doc_id: str) -> int:
    doc = _client().documents().get(documentId=doc_id).execute()
    body = doc.get("body", {}).get("content", [])
    if not body:
        return 1
    return body[-1].get("endIndex", 1) - 1  # exclude trailing newline


def _batch_update(doc_id: str, requests: list[dict[str, Any]]) -> None:
    _client().documents().batchUpdate(
        documentId=doc_id, body={"requests": requests}
    ).execute()
