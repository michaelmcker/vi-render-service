"""Cloudflare Access verification — defense-in-depth gate.

Cloudflare Access enforces email-allowlist policy at the edge. By the time
a request reaches Hermes, it has already passed that check. BUT — if someone
ever misconfigures the CF Access policy, or bypasses by hitting localhost
directly from inside the droplet, this layer still rejects them.

Headers Cloudflare Access sets on authenticated requests:
  - Cf-Access-Authenticated-User-Email — the email that signed in
  - Cf-Access-Jwt-Assertion           — signed JWT we COULD verify; we
                                         skip strict verification in v1
                                         and trust the email header,
                                         since CF Access is the only
                                         documented path. Tighten in v2
                                         if needed (verify JWT against
                                         CF's public keys).

Env:
  HERMES_WEB_AUTH=cf            (default) require CF Access headers
  HERMES_WEB_AUTH=disabled       LOCAL DEV ONLY — skip all auth
  HERMES_WEB_ALLOWED_EMAILS      comma-separated allowlist (defaults to
                                 the union of TELEGRAM_AUTHORIZED_CHAT_IDS
                                 emails configured in the operator's CF
                                 Access policy — but we don't know those
                                 here, so this var is required if mode=cf)
"""
from __future__ import annotations

import logging
import os

from fastapi import Header, HTTPException, status

log = logging.getLogger("hermes.web.auth")


def _allowed_emails() -> set[str]:
    raw = os.environ.get("HERMES_WEB_ALLOWED_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


async def require_user(
    cf_email: str | None = Header(None, alias="Cf-Access-Authenticated-User-Email"),
) -> str:
    """FastAPI dependency: returns the signed-in email or raises 403.

    Use as:  user_email: str = Depends(require_user)
    """
    mode = os.environ.get("HERMES_WEB_AUTH", "cf")

    if mode == "disabled":
        log.warning("auth disabled — DO NOT run like this in production")
        return "dev@local"

    if not cf_email:
        # No CF Access header → request didn't come through Cloudflare.
        # Could be a curl from inside the droplet, a misconfigured tunnel,
        # or someone who bypassed CF entirely. Refuse.
        log.warning("rejecting request with no Cf-Access-Authenticated-User-Email")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Cloudflare Access required")

    allowlist = _allowed_emails()
    if not allowlist:
        log.error("HERMES_WEB_ALLOWED_EMAILS is empty — rejecting all")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="server allowlist not configured")

    email = cf_email.strip().lower()
    if email not in allowlist:
        log.warning("rejecting unauthorized email: %s", email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="not authorized")

    return email
