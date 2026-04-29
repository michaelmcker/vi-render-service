"""Generate engagement-comment text and original post text for LinkedIn.

Comments are short (1-2 sentences), in Nikki's voice, designed to add value
to the discussion. Posts are longer-form (3-6 paragraphs), in her voice,
ready to queue in Buffer.
"""
from __future__ import annotations

import logging
from typing import Any

from .. import llm, profiles
from ..config import PROMPTS_DIR

log = logging.getLogger("hermes.linkedin.suggest")

COMMENT_PROMPT = PROMPTS_DIR / "linkedin_comment.md"
POST_PROMPT = PROMPTS_DIR / "linkedin_post.md"


def comment_for(post: dict[str, Any]) -> str:
    """Returns suggested comment text. May return '' if model decides no
    comment is appropriate."""
    voice = profiles.build_context(voice_context="default", max_chars=1500)
    payload = (
        f"VOICE CONTEXT:\n{voice}\n\n"
        f"POST AUTHOR: {post.get('author', '(unknown)')}\n"
        f"POST URL: {post.get('postUrl') or post.get('url', '')}\n\n"
        f"POST TEXT:\n{(post.get('text') or '')[:2500]}\n"
    )
    out = llm.run(COMMENT_PROMPT, payload, expect_json=False)
    text = out.strip() if isinstance(out, str) else ""
    if text.upper().startswith("{{SKIP}}"):
        return ""
    return text


def draft_post(topic: str, *, instruction: str = "") -> str:
    """Draft an original LinkedIn post on `topic` in her voice."""
    voice = profiles.build_context(voice_context="default", max_chars=1500)
    payload = (
        f"VOICE CONTEXT:\n{voice}\n\n"
        f"TOPIC:\n{topic}\n\n"
        f"INSTRUCTION:\n{instruction}\n"
    )
    out = llm.run(POST_PROMPT, payload, expect_json=False)
    return out.strip() if isinstance(out, str) else ""
