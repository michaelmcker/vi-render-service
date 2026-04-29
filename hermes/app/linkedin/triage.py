"""Classify scraped LinkedIn posts: which are engagement opps, which are
thought-leadership candidates, which to ignore.

Two outputs per post:
  - engage_priority: 'high' | 'medium' | 'skip'
      → 'high' or 'medium' triggers a Telegram suggestion with comment text
  - thought_leadership: bool
      → if True, archive verbatim into research/thought-leadership/ for
        weekly synthesis

Engagement thresholds + topic interests are configured in importance.yaml
under the linkedin: section.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from .. import llm, state
from ..config import HERMES_HOME, Importance, PROMPTS_DIR

log = logging.getLogger("hermes.linkedin.triage")

PROMPT = PROMPTS_DIR / "linkedin_triage.md"
TL_DIR = HERMES_HOME / "research" / "thought-leadership"


def classify(post: dict[str, Any]) -> dict[str, Any]:
    """Returns {engage_priority, thought_leadership, suggested_action}."""
    importance = Importance.load()
    cfg = importance.raw.get("linkedin", {})

    likes = int(post.get("likes") or post.get("likeCount") or 0)
    comments = int(post.get("comments") or post.get("commentCount") or 0)
    text = post.get("text") or post.get("postContent") or ""

    # Cheap heuristic gates first — avoid spending claude calls on obvious skips.
    if likes < cfg.get("min_likes_for_engagement", 5):
        return {"engage_priority": "skip", "thought_leadership": False,
                "suggested_action": "low engagement"}
    if not text.strip():
        return {"engage_priority": "skip", "thought_leadership": False,
                "suggested_action": "no text"}

    rules_yaml = yaml.safe_dump(cfg, sort_keys=False)
    payload = (
        f"IMPORTANCE_RULES:\n{rules_yaml}\n\n"
        f"POST:\n"
        f"  author: {post.get('author', '')}\n"
        f"  posted_at: {post.get('postedAt') or post.get('timestamp', '')}\n"
        f"  likes: {likes}\n"
        f"  comments: {comments}\n"
        f"  url: {post.get('postUrl') or post.get('post_url', '')}\n\n"
        f"TEXT:\n{text[:3000]}\n"
    )
    try:
        result = llm.run(PROMPT, payload, expect_json=True)
    except llm.LLMError:
        log.exception("linkedin triage failed; skipping post")
        return {"engage_priority": "skip", "thought_leadership": False,
                "suggested_action": "llm_failed"}
    if not isinstance(result, dict):
        return {"engage_priority": "skip", "thought_leadership": False,
                "suggested_action": "llm_unparseable"}
    return result


def archive_for_thought_leadership(post: dict[str, Any], *, source: str = "linkedin") -> Path:
    """Save the post verbatim to research/thought-leadership/{date}-{source}-{id}.md.

    The weekly thought_leadership job reads this directory.
    """
    TL_DIR.mkdir(parents=True, exist_ok=True)
    pid = _short_id(post)
    date = dt.date.today().isoformat()
    path = TL_DIR / f"{date}-{source}-{pid}.md"
    body = (
        f"# {post.get('author', '(unknown)')} — {date}\n\n"
        f"**Source**: {source}\n"
        f"**URL**: {post.get('postUrl') or post.get('url') or '(unknown)'}\n"
        f"**Likes**: {post.get('likes', 0)}\n"
        f"**Comments**: {post.get('comments', 0)}\n\n"
        f"---\n\n"
        f"{post.get('text') or post.get('postContent') or ''}\n"
    )
    path.write_text(body)
    log.info("archived thought-leadership candidate: %s", path)
    return path


_SLUG = re.compile(r"[^a-zA-Z0-9]+")


def _short_id(post: dict[str, Any]) -> str:
    raw = (post.get("postUrl") or post.get("url") or post.get("id")
           or post.get("text", "")[:30])
    return _SLUG.sub("-", str(raw))[-32:].strip("-") or "unknown"


def already_seen(post: dict[str, Any]) -> bool:
    """Dedup by URL or text-hash so we don't re-suggest the same post twice."""
    key = post.get("postUrl") or post.get("url") or _short_id(post)
    return state.already_seen("linkedin", key)


def mark_seen(post: dict[str, Any], result: dict[str, Any]) -> None:
    key = post.get("postUrl") or post.get("url") or _short_id(post)
    state.mark_seen("linkedin", key, result.get("engage_priority", "skip"),
                    (post.get("text") or "")[:120])
