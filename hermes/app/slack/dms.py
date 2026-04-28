"""DM poller (user token).

The Slack bot token can't see DMs Nikki has with anyone else. We use her user
token to poll `conversations.list(types=im,mpim)` then `conversations.history`
on each, and surface new messages from anyone other than her.

Polled rather than streamed: Slack RTM is deprecated for new apps. Polling at
60s feels real-time enough for DMs and stays well under rate limits.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .. import state
from . import auth, triage

log = logging.getLogger("hermes.slack.dms")


def poll_once(on_alert: Callable[[dict[str, Any]], None]) -> None:
    user = auth.user_client()
    nikki_id = auth.nikki_user_id()
    last_check = int(state.kv_get("slack_dm_last_check", "0") or "0")
    now = int(time.time())

    convos = user.conversations_list(types="im,mpim", limit=200, exclude_archived=True)
    for c in convos.get("channels", []):
        cid = c["id"]
        try:
            hist = user.conversations_history(channel=cid, oldest=str(last_check), limit=20)
        except Exception:
            log.exception("history fetch failed for %s", cid)
            continue

        for msg in reversed(hist.get("messages", [])):  # oldest -> newest
            if msg.get("user") == nikki_id or msg.get("bot_id"):
                continue
            ext_id = f"{cid}:{msg.get('ts')}"
            if state.already_seen("slack", ext_id):
                continue
            event = {**msg, "channel": cid, "channel_type": "im"}
            result = triage.classify(event, classifier_enabled=True)
            state.mark_seen("slack", ext_id, result["priority"], result.get("summary", ""))
            if result["priority"] in ("urgent", "today"):
                on_alert({**event, "_triage": result})

    state.kv_set("slack_dm_last_check", str(now))
