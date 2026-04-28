"""Socket Mode listener for Slack events.

Subscribes to `message.channels`, `message.groups`, and `app_mention`.
For every event, decides whether to triage:
  - DMs go through dms.py (user-token poll), NOT here.
  - @-mentions of Nikki -> always triage.
  - Messages in `monitor_channels` -> triage.
  - Everything else -> ignore.

Triaged messages are passed to slack.triage.classify() then to notify.send_*().
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from ..config import Importance
from . import auth, triage

log = logging.getLogger("hermes.slack.events")


def start(on_alert: Callable[[dict[str, Any]], None]) -> threading.Thread:
    """Run the Socket Mode listener in a background thread. Returns the thread."""
    importance = Importance.load()
    nikki_id = auth.nikki_user_id()
    monitored = set(_resolve_channel_ids(importance.slack.get("monitor_channels", [])))
    needs_response = importance.slack.get("needs_response_classifier", True)

    client = auth.socket_client()

    def handle(client_, req: SocketModeRequest):
        client_.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        if req.type != "events_api":
            return
        event = req.payload.get("event", {})
        try:
            _route(event, nikki_id=nikki_id, monitored=monitored,
                   needs_response=needs_response, on_alert=on_alert)
        except Exception:
            log.exception("error handling slack event")

    client.socket_mode_request_listeners.append(handle)
    client.connect()

    t = threading.Thread(target=lambda: threading.Event().wait(), daemon=True, name="slack-events")
    t.start()
    log.info("Slack Socket Mode connected (monitoring %d channels)", len(monitored))
    return t


def _route(event: dict[str, Any], *, nikki_id: str, monitored: set[str],
           needs_response: bool, on_alert: Callable) -> None:
    etype = event.get("type")
    subtype = event.get("subtype")
    if etype not in ("message", "app_mention"):
        return
    if subtype in ("message_changed", "message_deleted", "channel_join", "bot_message"):
        return
    if event.get("bot_id"):
        return  # ignore bot/integration noise
    if event.get("user") == nikki_id:
        return  # her own messages

    text = event.get("text", "")
    channel = event.get("channel", "")
    is_mention = f"<@{nikki_id}>" in text or etype == "app_mention"

    if is_mention or channel in monitored:
        result = triage.classify(event, classifier_enabled=needs_response)
        if result["priority"] in ("urgent", "today"):
            on_alert({**event, "_triage": result})


def _resolve_channel_ids(names_or_ids: list[str]) -> list[str]:
    """Turn '#deals-pipeline' into 'C0123ABC'. Pass-through if already an ID."""
    if not names_or_ids:
        return []
    out = []
    bot = auth.bot_client()
    cursor = None
    cache: dict[str, str] = {}
    while True:
        res = bot.conversations_list(types="public_channel,private_channel",
                                     limit=200, cursor=cursor)
        for ch in res.get("channels", []):
            cache[f"#{ch['name']}"] = ch["id"]
            cache[ch["id"]] = ch["id"]
        cursor = res.get("response_metadata", {}).get("next_cursor") or None
        if not cursor:
            break
    for n in names_or_ids:
        if n in cache:
            out.append(cache[n])
        else:
            log.warning("channel %r not found / bot not invited", n)
    return out
