"""Buffer API client — schedule LinkedIn posts via the official LinkedIn API
partner channel. No browser automation, no ToS exposure on her account.

Setup:
  1. buffer.com → connect her LinkedIn profile.
  2. publish.buffer.com → API access (paid tier required for API; Buffer
     "Essentials" plan covers it as of 2026).
  3. Get an access token (legacy v1 API or OAuth2 — token is simpler).
  4. List her connected profiles via GET /profiles.json; copy the LinkedIn
     profile id.
  5. Drop into .env:
       BUFFER_ACCESS_TOKEN=...
       BUFFER_LINKEDIN_PROFILE_ID=...

Flow:
  - Hermes generates a draft post (via claude -p with her voice)
  - Sends to Telegram for preview + approval
  - On approval, calls queue_post() to push into her Buffer queue
  - She reviews/edits in Buffer mobile, hits send, Buffer posts via official
    LinkedIn API.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import env

log = logging.getLogger("hermes.linkedin.buffer")

API_BASE = "https://api.bufferapp.com/1"


def _params() -> dict[str, str]:
    return {"access_token": env("BUFFER_ACCESS_TOKEN")}


def list_profiles() -> list[dict[str, Any]]:
    """Useful for setup — print the available profile ids."""
    r = httpx.get(f"{API_BASE}/profiles.json", params=_params(), timeout=15)
    r.raise_for_status()
    return r.json()


def queue_post(text: str, *, scheduled_at: int | None = None,
               attach_url: str | None = None) -> dict[str, Any]:
    """Push a post to her LinkedIn queue. Without scheduled_at, lands at the
    next slot in her configured Buffer schedule.

    Args:
      text:         the post body, ready to publish (her voice, edited).
      scheduled_at: unix timestamp; if None, Buffer picks next slot.
      attach_url:   optional URL to attach as a link preview.
    """
    payload = {
        "profile_ids[]": env("BUFFER_LINKEDIN_PROFILE_ID"),
        "text": text,
    }
    if scheduled_at:
        payload["scheduled_at"] = scheduled_at
    if attach_url:
        payload["media[link]"] = attach_url
    r = httpx.post(f"{API_BASE}/updates/create.json", params=_params(),
                   data=payload, timeout=20)
    r.raise_for_status()
    out = r.json()
    log.info("queued LinkedIn post in Buffer: id=%s", out.get("updates", [{}])[0].get("id"))
    return out


def list_pending() -> list[dict[str, Any]]:
    """Show what's queued — useful for /linkedin status command."""
    profile_id = env("BUFFER_LINKEDIN_PROFILE_ID")
    r = httpx.get(f"{API_BASE}/profiles/{profile_id}/updates/pending.json",
                  params=_params(), timeout=15)
    r.raise_for_status()
    return r.json().get("updates", [])
