"""Slack token loading.

Two tokens, both required:
  - Bot token (xoxb-)  — Socket Mode, Events API, posting in channels the bot
                         is in. Cannot read DMs.
  - User token (xoxp-) — Reads Nikki's DMs (bots can't see DMs they're not in)
                         and posts replies AS HER when she approves a draft.

Plus the App-Level Token (xapp-) for Socket Mode connection itself.

Tokens come from a single internal Slack app installed in the VI workspace
(see manifests/slack_app_manifest.yaml). After install, copy:
  - Bot User OAuth Token   → SLACK_BOT_TOKEN
  - User OAuth Token       → SLACK_USER_TOKEN
  - App-Level Token        → SLACK_APP_TOKEN  (create one with `connections:write`)
  - Signing Secret         → SLACK_SIGNING_SECRET
  - Nikki's Slack user ID  → SLACK_NIKKI_USER_ID
"""
from __future__ import annotations

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient

from ..config import env


def bot_client() -> WebClient:
    return WebClient(token=env("SLACK_BOT_TOKEN"))


def user_client() -> WebClient:
    """Posts and reads as Nikki. Treat with the same care as her password."""
    return WebClient(token=env("SLACK_USER_TOKEN"))


def socket_client() -> SocketModeClient:
    return SocketModeClient(
        app_token=env("SLACK_APP_TOKEN"),
        web_client=bot_client(),
    )


def nikki_user_id() -> str:
    return env("SLACK_NIKKI_USER_ID")
