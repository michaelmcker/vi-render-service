"""Run the slack_triage prompt against a single Slack event."""
from __future__ import annotations

import logging
from typing import Any

from .. import llm
from ..config import Importance, PROMPTS_DIR
from . import auth

log = logging.getLogger("hermes.slack.triage")

PROMPT = PROMPTS_DIR / "slack_triage.md"


def classify(event: dict[str, Any], *, classifier_enabled: bool) -> dict[str, Any]:
    """Returns {priority, needs_response, summary, signal_matches}."""
    importance = Importance.load()
    sender = _sender_display(event.get("user"))
    nikki_id = auth.nikki_user_id()
    text = event.get("text", "")

    is_dm = event.get("channel_type") == "im" or event.get("channel", "").startswith("D")
    is_mention = f"<@{nikki_id}>" in text

    if not classifier_enabled:
        return {
            "priority": "today",
            "needs_response": is_dm or is_mention,
            "summary": text[:120],
            "signal_matches": ["dm" if is_dm else "mention" if is_mention else "monitor_channel"],
        }

    rules_yaml = _yaml_dump(importance.slack)
    payload = (
        f"IMPORTANCE_RULES:\n{rules_yaml}\n\n"
        f"CONTEXT:\n"
        f"  sender_name: {sender['name']}\n"
        f"  sender_id: {event.get('user', '')}\n"
        f"  channel: {event.get('channel', '')}\n"
        f"  is_dm: {is_dm}\n"
        f"  is_mention_of_nikki: {is_mention}\n"
        f"  thread_ts: {event.get('thread_ts', '')}\n\n"
        f"MESSAGE:\n{text}\n"
    )
    try:
        result = llm.run(PROMPT, payload, expect_json=True)
    except llm.LLMError:
        log.exception("slack triage failed; defaulting to 'today'")
        return {"priority": "today", "needs_response": True, "summary": text[:120],
                "signal_matches": ["llm_failed"]}
    if not isinstance(result, dict) or "priority" not in result:
        return {"priority": "today", "needs_response": True, "summary": text[:120],
                "signal_matches": ["llm_unparseable"]}
    return result


def _sender_display(user_id: str | None) -> dict[str, str]:
    if not user_id:
        return {"name": "(unknown)", "email": ""}
    try:
        info = auth.bot_client().users_info(user=user_id)["user"]
        return {
            "name": info.get("real_name") or info.get("name") or user_id,
            "email": info.get("profile", {}).get("email", ""),
        }
    except Exception:
        return {"name": user_id, "email": ""}


def _yaml_dump(d: dict[str, Any]) -> str:
    import yaml
    return yaml.safe_dump(d, sort_keys=False, default_flow_style=False)
