"""Google OAuth — minimum-privilege scopes for v1.

V1 grants only:
  - gmail.readonly + gmail.compose   → read mail, create drafts. NO send, NO trash, NO delete.
  - calendar.readonly                → read events for the morning briefing context.

Drive, Docs, and Sheets are NOT requested in v1. When those features are wired
up (research briefs to Drive, spreadsheet-fill workflows, etc.) we extend
SCOPES and re-run `python -m app.oauth_setup google`. Google will issue a
fresh refresh token covering the new scopes.

Why narrow on Gmail: with gmail.compose + gmail.readonly, the Google API will
REFUSE any call to messages.trash, messages.delete, threads.delete, or
batchModify-to-trash. Even a buggy code path cannot delete or trash mail.
The only "delete" gmail.compose permits is drafts.delete (removing a Hermes-
authored draft) — never a real email.
"""
from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from ..config import SECRETS_DIR

CLIENT_SECRETS = SECRETS_DIR / "google_client.json"
TOKEN_PATH = SECRETS_DIR / "google_token.json"

# Order matters for Google's consent screen display.
# To extend (Drive/Docs/Sheets), append the scope and re-run `oauth_setup google`.
SCOPES = [
    # Gmail: READ + CREATE-DRAFT only. No modify, no send, no trash, no delete.
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    # Calendar: READ ONLY. No create, no modify, no delete.
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]


def authorize() -> Credentials:
    """Run the one-time interactive OAuth flow on the Mac. Saves a refresh token."""
    if not CLIENT_SECRETS.exists():
        raise FileNotFoundError(
            f"Missing {CLIENT_SECRETS}. Download the OAuth client JSON from "
            "Google Cloud Console (Credentials → OAuth client → Desktop app) "
            "and save it there."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS), SCOPES)
    creds = flow.run_local_server(port=8080, prompt="consent", access_type="offline")
    _save(creds)
    return creds


def get_credentials() -> Credentials:
    """Load saved refresh token; transparently refresh access token when expired."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(
            f"No saved Google token at {TOKEN_PATH}. "
            "Run: python -m app.oauth_setup google"
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save(creds)
        else:
            raise RuntimeError(
                "Google credentials invalid and not refreshable. "
                "Run: python -m app.oauth_setup google"
            )
    return creds


def _save(creds: Credentials) -> None:
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
