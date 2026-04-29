"""LinkedIn scanner — daemon entry point.

Twice daily (8am + 4pm her time):
  1. Scrape watched-people activity pages via Playwright (secondary account).
  2. Scrape the secondary account's feed for thought-leadership candidates.
  3. For each new post:
     - Classify (triage.classify).
     - If thought_leadership=true: archive verbatim to research/thought-leadership/.
     - If engage_priority='high': push a Telegram suggestion immediately.
     - If 'medium': leave for the /linkedin command and the morning batch.
  4. Mark seen so we don't re-suggest.
"""
from __future__ import annotations

import logging
from typing import Any

import yaml

from .. import notify
from ..config import Importance
from . import playwright_scanner, suggest, triage

log = logging.getLogger("hermes.linkedin.scanner")


def run_once() -> dict[str, int]:
    """Returns counts: {watched_scanned, feed_scanned, new, engaged_high,
                        engaged_medium, archived}."""
    counts = {"watched_scanned": 0, "feed_scanned": 0, "new": 0,
              "engaged_high": 0, "engaged_medium": 0, "archived": 0}

    importance = Importance.load()
    watched = importance.raw.get("linkedin", {}).get("watched_people", []) or []

    posts: list[dict[str, Any]] = []

    # 1. Watched people (engagement opps with their suggested comment text).
    try:
        watched_posts = playwright_scanner.scan_watched_people(watched)
        counts["watched_scanned"] = len(watched_posts)
        posts.extend(watched_posts)
    except playwright_scanner.LinkedInBlockedError as e:
        notify.send_text(f"⚠️ LinkedIn scanner blocked: {e}", urgent=True, kind="system")
        return counts
    except Exception:
        log.exception("watched-people scan failed")

    # 2. Feed (thought-leadership candidates).
    try:
        feed_posts = playwright_scanner.scan_feed_for_thought_leadership()
        counts["feed_scanned"] = len(feed_posts)
        posts.extend(feed_posts)
    except playwright_scanner.LinkedInBlockedError:
        # already pinged above if it was blocked there; if it triggers here only,
        # ping once more.
        notify.send_text("⚠️ LinkedIn feed scanner blocked. Cookies may have expired.",
                         urgent=True, kind="system")
        return counts
    except Exception:
        log.exception("feed scan failed")

    # 3. Triage + route.
    for post in posts:
        if triage.already_seen(post):
            continue
        counts["new"] += 1
        result = triage.classify(post)
        triage.mark_seen(post, result)

        if result.get("thought_leadership"):
            triage.archive_for_thought_leadership(post)
            counts["archived"] += 1

        # Only suggest engagement on watched-people posts. Feed posts are
        # for thought-leadership archiving only — she doesn't engage from
        # her main account on random feed posts via Hermes.
        if post.get("source") == "watched_person":
            prio = result.get("engage_priority")
            if prio == "high":
                _ping_engagement_opp(post, result, urgent=True)
                counts["engaged_high"] += 1
            elif prio == "medium":
                counts["engaged_medium"] += 1

    return counts


def _ping_engagement_opp(post: dict[str, Any], result: dict[str, Any],
                         *, urgent: bool) -> None:
    comment = suggest.comment_for(post)
    if not comment:
        return
    author = post.get("author", "(unknown)")
    url = post.get("postUrl") or ""
    watched_for = post.get("watched_for", "")
    header = f"💬 *LinkedIn — {author}*"
    if watched_for:
        header += f"  _({watched_for})_"

    text = (
        f"{header}\n"
        f"{result.get('suggested_action', '')}\n\n"
        f"> _{(post.get('text') or '')[:240]}…_\n\n"
        f"*Suggested comment* — long-press to copy:\n"
        f"```\n{comment}\n```"
    )
    keyboard: list[list[dict[str, str]]] = []
    if url:
        keyboard.append([{"text": "📎 Open post on your phone", "url": url}])
    keyboard.append([
        {"text": "🗑 Skip", "callback_data": f"linkedin_skip:{_safe_id(post)}"},
    ])
    notify.send_text(text, kind="urgent" if urgent else "today",
                     keyboard=keyboard, urgent=urgent)


def _safe_id(post: dict[str, Any]) -> str:
    raw = post.get("postUrl") or post.get("id") or ""
    return str(raw)[-48:].replace(":", "_").replace("/", "_") or "x"
