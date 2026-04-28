"""Slack actions: read a thread, post a reply AS HER (after she approves)."""
from __future__ import annotations

import logging
from typing import Any

from . import auth

log = logging.getLogger("hermes.slack.actions")


def fetch_thread(channel: str, thread_ts: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """Returns messages in chronological order. Uses the user token so DMs are visible."""
    user = auth.user_client()
    res = user.conversations_replies(channel=channel, ts=thread_ts, limit=limit)
    return res.get("messages", [])


def fetch_recent(channel: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """Recent context for a non-threaded channel message."""
    user = auth.user_client()
    res = user.conversations_history(channel=channel, limit=limit)
    msgs = res.get("messages", [])
    return list(reversed(msgs))  # oldest -> newest


def post_as_her(channel: str, text: str, *, thread_ts: str | None = None) -> dict[str, Any]:
    """Post a message in Nikki's name. ONLY call this after she approves a draft."""
    user = auth.user_client()
    res = user.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts, as_user=True)
    log.info("posted as Nikki to %s ts=%s", channel, res.get("ts"))
    return res


def react_as_her(channel: str, ts: str, emoji: str) -> None:
    user = auth.user_client()
    try:
        user.reactions_add(channel=channel, timestamp=ts, name=emoji.strip(":"))
    except Exception:
        log.exception("react failed")


def thread_to_text(messages: list[dict[str, Any]]) -> str:
    """Format a Slack thread for the LLM prompt."""
    lines = []
    for m in messages:
        sender = m.get("user", "?")
        text = m.get("text", "")
        lines.append(f"[{sender}] {text}")
    return "\n".join(lines)
