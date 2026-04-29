"""Outbound Telegram notifications.

Implements the noise budget (max alerts/hour) and quiet hours.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import zoneinfo
from typing import Any

import httpx

from . import state
from .config import Importance, env

log = logging.getLogger("hermes.notify")


def _primary_chat_id() -> str:
    """Nikki's chat. Falls back to legacy TELEGRAM_CHAT_ID for migration."""
    val = os.environ.get("TELEGRAM_PRIMARY_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    if not val:
        raise RuntimeError(
            "TELEGRAM_PRIMARY_CHAT_ID not set (or legacy TELEGRAM_CHAT_ID)"
        )
    return val


def _authorized_chat_ids() -> list[str]:
    """Allowlist for commands + system-ping broadcasts."""
    raw = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "")
    if raw:
        return [x.strip() for x in raw.split(",") if x.strip()]
    # Migration fallback — single primary chat is the only authorized one.
    return [_primary_chat_id()]


def send_text(text: str, *, kind: str = "system",
              keyboard: list[list[dict[str, str]]] | None = None,
              urgent: bool = False, audience: str = "primary") -> bool:
    """Send a Telegram message. Returns True if any send succeeded.

    audience:
        "primary"  — only Nikki's chat (briefings, drafts, alerts)
        "all"      — both authorized chats (system errors, health pings)
        "operator" — operator only (rare; explicit operator-side fetches)
    """
    if not urgent and _suppressed(kind):
        log.info("suppressed %s message (quiet hours / budget)", kind)
        return False

    targets = _resolve_audience(audience)
    token = env("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent_any = False

    for chat_id in targets:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = {"inline_keyboard": keyboard}
        try:
            r = httpx.post(url, json=payload, timeout=15)
            r.raise_for_status()
            sent_any = True
        except httpx.HTTPError:
            log.exception("telegram send failed for chat %s", chat_id)

    if sent_any:
        state.log_notify(kind)
    return sent_any


def _resolve_audience(audience: str) -> list[str]:
    if audience == "primary":
        return [_primary_chat_id()]
    if audience == "all":
        # Dedup while preserving order: primary first, then any operator-only.
        primary = _primary_chat_id()
        out = [primary]
        for cid in _authorized_chat_ids():
            if cid != primary and cid not in out:
                out.append(cid)
        return out
    if audience == "operator":
        primary = _primary_chat_id()
        return [c for c in _authorized_chat_ids() if c != primary]
    raise ValueError(f"unknown audience: {audience!r}")


def alert_email(message: dict[str, Any], triage: dict[str, Any]) -> None:
    """Push an urgent or today-priority email to Telegram with action buttons."""
    sender = message.get("from", "")
    subject = message.get("subject", "(no subject)")
    summary = triage.get("summary", "")
    text = (
        f"*{_priority_emoji(triage['priority'])} {sender}*\n"
        f"_{subject}_\n\n"
        f"{summary}"
    )
    keyboard = [[
        {"text": "Draft reply", "callback_data": f"email_draft:{message['id']}"},
        {"text": "View", "callback_data": f"email_view:{message['id']}"},
    ], [
        {"text": "Snooze 1d", "callback_data": f"email_snooze:{message['id']}:86400"},
        {"text": "Mute thread", "callback_data": f"email_mute:{message['thread_id']}"},
    ]]
    send_text(text, kind="urgent" if triage["priority"] == "urgent" else "today",
              keyboard=keyboard, urgent=triage["priority"] == "urgent")


def alert_slack(event: dict[str, Any], triage: dict[str, Any]) -> None:
    """Push a Slack mention/DM/monitored-channel hit to Telegram."""
    sender = event.get("user", "?")
    channel = event.get("channel", "")
    summary = triage.get("summary", event.get("text", "")[:120])
    text = (
        f"*{_priority_emoji(triage['priority'])} Slack — {sender}*\n"
        f"_{channel}_\n\n"
        f"{summary}"
    )
    msg_ts = event.get("ts", "")
    keyboard = [[
        {"text": "Draft reply", "callback_data": f"slack_draft:{channel}:{msg_ts}"},
        {"text": "👍 react", "callback_data": f"slack_react:{channel}:{msg_ts}"},
    ], [
        {"text": "Snooze 1h", "callback_data": f"slack_snooze:{channel}:{msg_ts}:3600"},
        {"text": "Mute thread", "callback_data": f"slack_mute:{channel}:{msg_ts}"},
    ]]
    send_text(text, kind="urgent" if triage["priority"] == "urgent" else "today",
              keyboard=keyboard, urgent=triage["priority"] == "urgent")


def daily_briefing(items: list[dict[str, Any]]) -> None:
    """Single message at 7am with everything she should know about today."""
    if not items:
        send_text("Morning. Inbox is quiet. ☀️", kind="briefing", urgent=True)
        return
    lines = [f"*Morning briefing — {dt.date.today().isoformat()}*", ""]
    for it in items[:20]:
        lines.append(f"• {_priority_emoji(it['priority'])} {it['summary']}")
    send_text("\n".join(lines), kind="briefing", urgent=True)


def _priority_emoji(p: str) -> str:
    return {"urgent": "🔥", "today": "📌", "fyi": "·", "mute": "🔇"}.get(p, "•")


def _suppressed(kind: str) -> bool:
    if kind == "briefing":
        return False  # always show briefings
    importance = Importance.load()
    if _in_quiet_hours(importance.budget.get("quiet_hours")):
        return True
    cap = importance.budget.get("max_alerts_per_hour", 8)
    return state.alerts_in_last_hour() >= cap


def _in_quiet_hours(window: str | None) -> bool:
    if not window:
        return False
    tz = zoneinfo.ZoneInfo(env("HERMES_TIMEZONE", "America/New_York"))
    now = dt.datetime.now(tz).time()
    start_s, end_s = window.split("-")
    start = dt.time.fromisoformat(start_s)
    end = dt.time.fromisoformat(end_s)
    if start <= end:
        return start <= now <= end
    return now >= start or now <= end  # crosses midnight
