"""LinkedIn read via Playwright + a SECONDARY LinkedIn account.

Why a secondary account: any browser automation against LinkedIn carries
ToS-violation risk. We isolate that risk to a burner account that has no
connection to Nikki's real identity. Her main account is never automated
against. The action (commenting, liking) happens manually on her phone via
her real account, after Hermes pings her with a link.

Setup (one-time):
  1. Create a new LinkedIn account with a different email (e.g. an alias).
     Skip a real photo; minimal profile is fine.
  2. Have it follow ~30-50 industry voices Nikki cares about. This populates
     the secondary feed with thought-leadership-grade content.
  3. Run: `python -m app.oauth_setup linkedin-cookies`
     A non-headless Playwright window opens. Sign in. Close the window when
     the home feed loads. Cookies are saved to
     secrets/linkedin_secondary_cookies.json (chmod 600).
  4. Add watched-people LinkedIn URLs to config/importance.yaml under
     linkedin.watched_people, OR add via Telegram: /lwatch <url> <name>.

The scanner:
  - Opens Playwright with saved cookies (headless on the daemon Mac).
  - For each watched person, visits their /recent-activity/all/ page and
     scrapes recent posts with engagement metrics.
  - Visits the secondary account's main feed and scrapes for thought-
     leadership candidates (high-engagement industry posts).
  - Throttles aggressively (2-3s between page actions, max 15 profiles/run).
  - On bot-challenge / login-redirect, aborts cleanly and pings Nikki to
     re-login.

Risk profile: the secondary account COULD eventually get flagged. If it
does, no impact on her real account. Re-create the secondary, re-run
oauth_setup linkedin-cookies, resume.
"""
from __future__ import annotations

import json
import logging
import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..config import SECRETS_DIR, env

log = logging.getLogger("hermes.linkedin.playwright")

COOKIES_PATH = SECRETS_DIR / "linkedin_secondary_cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Safari/605.1.15"
)

# Throttle between page actions. Tuple = (min_seconds, max_seconds).
THROTTLE_BETWEEN_ACTIONS = (2.0, 4.0)
THROTTLE_BETWEEN_PROFILES = (4.0, 8.0)

MAX_PROFILES_PER_RUN = 15
MAX_FEED_POSTS = 30


class LinkedInBlockedError(RuntimeError):
    """Raised when LinkedIn redirects to a login or challenge page."""


def _throttle(window: tuple[float, float]) -> None:
    time.sleep(random.uniform(*window))


def save_cookies_interactive() -> None:
    """One-time setup: launch a real browser, let her sign in, save cookies."""
    from playwright.sync_api import sync_playwright

    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(user_agent=USER_AGENT)
        page = ctx.new_page()
        page.goto("https://www.linkedin.com/login")
        print("\n👉 Sign in to the SECONDARY LinkedIn account in the browser window.")
        print("   When you see the home feed, return here and press Enter.\n")
        input("Press Enter after the home feed loads… ")
        cookies = ctx.cookies()
        COOKIES_PATH.write_text(json.dumps(cookies, indent=2))
        COOKIES_PATH.chmod(0o600)
        print(f"✅ Saved {len(cookies)} cookies to {COOKIES_PATH}")
        browser.close()


@contextmanager
def _browser() -> Iterator[Any]:
    """Headless Chromium with saved cookies. Imports playwright lazily."""
    from playwright.sync_api import sync_playwright

    if not COOKIES_PATH.exists():
        raise LinkedInBlockedError(
            f"No cookies at {COOKIES_PATH}. Run "
            "`python -m app.oauth_setup linkedin-cookies` to seed them."
        )
    cookies = json.loads(COOKIES_PATH.read_text())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctx = browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 1600})
        ctx.add_cookies(cookies)
        try:
            yield ctx
        finally:
            browser.close()


def scan_watched_people(watched: list[dict[str, str]]) -> list[dict[str, Any]]:
    """For each entry in watched (with linkedin_url + name), grab recent posts.

    Returns post dicts with {author, text, postUrl, likes, comments, postedAt,
    source: 'watched_person', watched_for: <reason>}.
    """
    out: list[dict[str, Any]] = []
    if not watched:
        return out

    with _browser() as ctx:
        page = ctx.new_page()
        for entry in watched[:MAX_PROFILES_PER_RUN]:
            url = (entry.get("linkedin_url") or "").rstrip("/")
            if not url:
                continue
            activity_url = f"{url}/recent-activity/all/"
            try:
                page.goto(activity_url, wait_until="domcontentloaded", timeout=20000)
                _ensure_logged_in(page)
                _throttle(THROTTLE_BETWEEN_ACTIONS)
                posts = _scrape_post_cards(page, source="watched_person",
                                          author_default=entry.get("name", ""),
                                          watched_for=entry.get("reason", ""))
                out.extend(posts)
            except LinkedInBlockedError:
                raise
            except Exception:
                log.exception("failed scraping %s", activity_url)
            _throttle(THROTTLE_BETWEEN_PROFILES)
    return out


def scan_feed_for_thought_leadership() -> list[dict[str, Any]]:
    """Scrolls the secondary account's home feed and returns recent post dicts."""
    out: list[dict[str, Any]] = []
    with _browser() as ctx:
        page = ctx.new_page()
        try:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=25000)
            _ensure_logged_in(page)
            _throttle(THROTTLE_BETWEEN_ACTIONS)
            # Scroll a few times to load more posts.
            for _ in range(3):
                page.mouse.wheel(0, 4000)
                _throttle(THROTTLE_BETWEEN_ACTIONS)
            out = _scrape_post_cards(page, source="feed", limit=MAX_FEED_POSTS)
        except LinkedInBlockedError:
            raise
        except Exception:
            log.exception("feed scrape failed")
    return out


def _ensure_logged_in(page: Any) -> None:
    """If we got bounced to /login, /uas/login, or a challenge page, abort."""
    url = page.url
    if "/login" in url or "/uas/" in url or "/checkpoint/" in url:
        raise LinkedInBlockedError(
            "LinkedIn redirected to a login/challenge page. "
            "Cookies likely expired. Re-run "
            "`python -m app.oauth_setup linkedin-cookies`."
        )


def _scrape_post_cards(page: Any, *, source: str, author_default: str = "",
                       watched_for: str = "", limit: int = 50) -> list[dict[str, Any]]:
    """Best-effort scrape of post cards. LinkedIn's DOM changes; treat each
    selector as a hint and degrade to '' on failure rather than crashing."""
    cards = page.locator("div.feed-shared-update-v2, .occludable-update").all()[:limit]
    results: list[dict[str, Any]] = []
    for card in cards:
        try:
            text = _safe_text(card, ".update-components-text, .feed-shared-text")
            author = _safe_text(card, ".update-components-actor__title") or author_default
            posted_at = _safe_text(card, ".update-components-actor__sub-description")
            post_url = _safe_attr(card, "a.app-aware-link[href*='/feed/update/']", "href")
            likes = _safe_int(card, ".social-details-social-counts__reactions-count, "
                                    ".social-details-social-counts__count-value")
            comments = _safe_int(card, ".social-details-social-counts__comments")
            if not text and not post_url:
                continue
            results.append({
                "text": text,
                "author": author,
                "postUrl": post_url,
                "postedAt": posted_at,
                "likes": likes,
                "comments": comments,
                "source": source,
                "watched_for": watched_for,
            })
        except Exception:
            continue
    return results


def _safe_text(scope: Any, selector: str) -> str:
    try:
        loc = scope.locator(selector).first
        if loc.count() == 0:
            return ""
        return (loc.inner_text(timeout=2000) or "").strip()
    except Exception:
        return ""


def _safe_attr(scope: Any, selector: str, attr: str) -> str:
    try:
        loc = scope.locator(selector).first
        if loc.count() == 0:
            return ""
        return (loc.get_attribute(attr, timeout=2000) or "").strip()
    except Exception:
        return ""


def _safe_int(scope: Any, selector: str) -> int:
    raw = _safe_text(scope, selector)
    digits = "".join(c for c in raw if c.isdigit())
    return int(digits) if digits else 0
