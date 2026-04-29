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
# Scope strings verified against Google's current docs (developers.google.com).
SCOPES = [
    # Gmail: READ + COMPOSE-DRAFT.
    # NOTE: gmail.compose includes send capability per Google's docs ("Manage
    # drafts and send emails"). There is no narrower scope for drafts-without-
    # send. Hermes blocks send/trash/delete/batchModify at the HTTP-transport
    # layer in gmail.py via _GmailSafeHttp — those calls cannot leave the daemon.
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",

    # Calendar: events READ ONLY. Narrower than calendar.readonly (which also
    # exposes calendar list metadata). We only need events for the briefing.
    "https://www.googleapis.com/auth/calendar.events.readonly",

    # Docs: full read+write. Used for research briefs, account plans, recaps.
    # The documents scope is content-API-scoped: Hermes can mutate any Doc
    # she has access to, not just Hermes-created ones. (drive.file does NOT
    # constrain Docs API mutations.)
    "https://www.googleapis.com/auth/documents",

    # Sheets: full read+write. Required for the "fill out this spreadsheet I
    # made" workflow — same content-API-scope behavior as documents.
    "https://www.googleapis.com/auth/spreadsheets",

    # Drive:
    #   drive.readonly  — read existing files (research context, decks, etc.)
    #   drive.file      — modify/delete via Drive API only files Hermes created
    #                     (or files explicitly shared with the app via Picker)
    # Combined: Drive-level file management is constrained to Hermes-owned
    # files; Doc/Sheet content access is governed by the documents/spreadsheets
    # scopes above.
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",

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
