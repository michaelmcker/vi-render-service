"""Gmail — read + create-draft only.

Hard guarantees:
- No function in this module sends mail.
- No function in this module deletes, trashes, or modifies labels on real
  messages. The OAuth scope (gmail.compose + gmail.readonly) prevents it
  at the API edge even if buggy code tried.
- The only API endpoint that can mutate state is users().drafts().create().

If you ever need to extend this module, the rule is: drafts only. Send, trash,
delete, and label-modification stay outside Hermes — Nikki does those in Gmail.
"""
from __future__ import annotations

import base64
import logging
from email.message import EmailMessage
from typing import Any

from googleapiclient.discovery import build

from .auth import get_credentials

log = logging.getLogger("hermes.gmail")


def _client():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def list_unread(after_unix: int | None = None, max_results: int = 50) -> list[dict[str, Any]]:
    """Returns full message dicts for unread mail in INBOX since `after_unix`."""
    g = _client()
    q = "is:unread in:inbox"
    if after_unix:
        q += f" after:{after_unix}"
    res = g.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
    return [get_message(m["id"]) for m in res.get("messages", [])]


def get_message(message_id: str) -> dict[str, Any]:
    g = _client()
    msg = g.users().messages().get(userId="me", id=message_id, format="full").execute()
    return _normalize(msg)


def get_thread(thread_id: str) -> dict[str, Any]:
    g = _client()
    t = g.users().threads().get(userId="me", id=thread_id, format="full").execute()
    t["messages"] = [_normalize(m) for m in t.get("messages", [])]
    return t


def create_draft(thread_id: str, in_reply_to_message_id: str, body_text: str) -> dict[str, Any]:
    """Drop a reply draft into Gmail Drafts. Never sends. Returns the draft id."""
    g = _client()
    src = g.users().messages().get(
        userId="me", id=in_reply_to_message_id, format="metadata",
        metadataHeaders=["From", "To", "Cc", "Subject", "Message-ID", "References"],
    ).execute()
    headers = {h["name"].lower(): h["value"] for h in src["payload"]["headers"]}

    em = EmailMessage()
    em.set_content(body_text)
    em["To"] = headers.get("from", "")
    cc = headers.get("cc")
    if cc:
        em["Cc"] = cc
    subject = headers.get("subject", "")
    if subject and not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"
    em["Subject"] = subject
    if msg_id := headers.get("message-id"):
        em["In-Reply-To"] = msg_id
        refs = headers.get("references", "")
        em["References"] = (refs + " " + msg_id).strip()

    raw = base64.urlsafe_b64encode(em.as_bytes()).decode()
    draft = g.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw, "threadId": thread_id}},
    ).execute()
    log.info("created draft %s in thread %s", draft.get("id"), thread_id)
    return draft


def _normalize(msg: dict[str, Any]) -> dict[str, Any]:
    """Pull the headers and body text into a flat shape the rest of the daemon uses."""
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = _extract_body(msg.get("payload", {}))
    return {
        "id": msg["id"],
        "thread_id": msg["threadId"],
        "internal_date": int(msg.get("internalDate", 0)) // 1000,
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "cc": headers.get("cc", ""),
        "subject": headers.get("subject", ""),
        "snippet": msg.get("snippet", ""),
        "body": body,
        "labels": msg.get("labelIds", []),
    }


def _extract_body(payload: dict[str, Any]) -> str:
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        mt = part.get("mimeType", "")
        if mt == "text/plain":
            data = part.get("body", {}).get("data")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []) or []:
        text = _extract_body(part)
        if text:
            return text
    return ""


# Explicit guard: any future contributor who tries to send mail trips this.
def send(*_args: Any, **_kwargs: Any) -> None:  # noqa: D401 - intentionally a tripwire
    raise RuntimeError(
        "Hermes never sends mail. Drafts go to Nikki's Drafts folder; she sends. "
        "Do not add a send() implementation."
    )
