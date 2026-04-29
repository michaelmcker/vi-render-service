"""Email triage glue. Calls llm.run() with the triage prompt."""
from __future__ import annotations

import logging
from typing import Any

import yaml

from . import llm, state
from .config import Importance, PROMPTS_DIR

log = logging.getLogger("hermes.classify")
PROMPT = PROMPTS_DIR / "triage.md"


def classify_email(message: dict[str, Any]) -> dict[str, Any]:
    """Returns {priority, category, summary, needs_response, suggested_actions, signal_matches}."""
    if state.is_snoozed("gmail", message["id"]):
        return {"priority": "mute", "summary": "(snoozed)", "needs_response": False,
                "category": "other", "signal_matches": ["snoozed"], "suggested_actions": []}

    importance = Importance.load()
    rules_yaml = yaml.safe_dump(importance.email, sort_keys=False)
    body = message.get("body", "") or message.get("snippet", "")
    payload = (
        f"IMPORTANCE_RULES:\n{rules_yaml}\n\n"
        f"EMAIL:\n"
        f"From: {message.get('from','')}\n"
        f"To: {message.get('to','')}\n"
        f"Cc: {message.get('cc','')}\n"
        f"Subject: {message.get('subject','')}\n\n"
        f"{body[:6000]}\n"
    )
    try:
        result = llm.run(PROMPT, payload, expect_json=True)
    except llm.LLMError:
        log.exception("triage failed; defaulting to 'today'")
        return {"priority": "today", "summary": message.get("subject", "")[:80],
                "needs_response": True, "category": "other",
                "signal_matches": ["llm_failed"], "suggested_actions": []}
    if not isinstance(result, dict) or "priority" not in result:
        return {"priority": "today", "summary": message.get("subject", "")[:80],
                "needs_response": True, "category": "other",
                "signal_matches": ["llm_unparseable"], "suggested_actions": []}
    return result
