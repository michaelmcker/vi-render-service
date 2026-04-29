"""One-time OAuth + connectivity setup.

Usage:
    python -m app.oauth_setup google             # run Google OAuth flow
    python -m app.oauth_setup linkedin-cookies   # save secondary LinkedIn cookies
    python -m app.oauth_setup test-telegram      # send a test message
    python -m app.oauth_setup test-slack         # check Slack tokens
    python -m app.oauth_setup test-claude        # confirm `claude -p` works
    python -m app.oauth_setup all                # do everything in sequence
"""
from __future__ import annotations

import sys

from . import llm
from .config import PROMPTS_DIR


def _google() -> None:
    from .google.auth import authorize, SCOPES
    print("Requesting Google scopes:")
    for s in SCOPES:
        print(f"  - {s}")
    print("\nOpening browser for consent…")
    authorize()
    print("✅ Google connected. Refresh token saved to secrets/google_token.json")


def _telegram() -> None:
    from . import notify
    ok = notify.send_text("Hermes setup test ping. If you see this, Telegram is wired up.",
                          urgent=True, kind="system")
    print("✅ sent" if ok else "❌ failed (check TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")


def _slack() -> None:
    from .slack.auth import bot_client, user_client, nikki_user_id
    bot_id = bot_client().auth_test().get("user_id")
    user_id = user_client().auth_test().get("user_id")
    nikki = nikki_user_id()
    print(f"Bot user:  {bot_id}")
    print(f"User token signs in as: {user_id}")
    print(f"Configured Nikki id:    {nikki}")
    if user_id != nikki:
        print("⚠️  User token does NOT belong to Nikki. Fix SLACK_USER_TOKEN.")
    else:
        print("✅ Slack tokens look right.")


def _claude() -> None:
    out = llm.run(PROMPTS_DIR / "triage.md",
                  '{"from":"test@example.com","subject":"hi","body":"ignore me"}',
                  expect_json=False, timeout=30)
    print(f"`claude -p` returned ({len(out)} chars). ✅")


def _linkedin_cookies() -> None:
    from .linkedin.playwright_scanner import save_cookies_interactive
    save_cookies_interactive()


COMMANDS = {
    "google": _google,
    "linkedin-cookies": _linkedin_cookies,
    "test-telegram": _telegram,
    "test-slack": _slack,
    "test-claude": _claude,
}


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "all":
        for name in ("test-claude", "test-telegram", "google", "test-slack"):
            print(f"\n=== {name} ===")
            try:
                COMMANDS[name]()
            except Exception as e:
                print(f"❌ {name}: {e}")
        return
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(2)
    COMMANDS[cmd]()


if __name__ == "__main__":
    main()
