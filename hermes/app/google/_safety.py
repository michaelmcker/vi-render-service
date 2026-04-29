"""HTTP-transport safety wrapper for Google APIs.

Hermes policy (canonical reference: SAFETY.md):
  - NEVER send mail.
  - NEVER trash, untrash, or permanently delete mail.
  - NEVER delete any Drive file (Doc, Sheet, or otherwise).
  - NEVER empty Drive trash.
  - NEVER move a file to Drive trash via the API.

Enforcement happens here, at the HTTP transport layer, so it applies regardless
of what OAuth scopes are granted. Even if a contributor accidentally widens a
scope or adds a code path, the destructive request is refused before it
reaches Google.

To add a destructive operation in the future, you must:
  1. Update SAFETY.md with the rationale.
  2. Wire the call through `hermes.policy.require_double_confirm()`.
  3. Explicitly carve it out of the block list here, with a code comment
     pointing at the SAFETY.md change.
"""
from __future__ import annotations

import httplib2
from google_auth_httplib2 import AuthorizedHttp

from .auth import get_credentials


class GoogleSafeHttp(httplib2.Http):
    """Refuses destructive Google API calls regardless of OAuth scope."""

    def request(self, uri, method="GET", body=None, headers=None,
                redirections=5, connection_type=None):
        self._check(method, uri, body)
        return super().request(uri, method, body, headers, redirections, connection_type)

    def _check(self, method: str, uri: str, body) -> None:
        # ── Gmail ──────────────────────────────────────────────────
        if "/gmail/v1/" in uri:
            for frag in ("/messages/send", "/drafts/send",
                         "/trash", "/untrash",
                         "/batchDelete", "/batchModify"):
                if frag in uri:
                    self._refuse(method, uri, f"Gmail destructive op: {frag}")
            # Permanent delete on real messages/threads.
            # DELETE on /drafts/{id} is allowed (cleaning up Hermes-authored drafts).
            if method == "DELETE" and ("/messages/" in uri or "/threads/" in uri):
                self._refuse(method, uri, "Gmail permanent delete of messages/threads")

        # ── Drive ──────────────────────────────────────────────────
        if "/drive/v3/" in uri or "/drive/v2/" in uri:
            if method == "DELETE":
                self._refuse(method, uri, "Drive file/folder delete")
            if "/emptyTrash" in uri or "/empty_trash" in uri:
                self._refuse(method, uri, "Drive empty trash")
            # Block files.update / files.patch with trashed=true in the body.
            if body and method in ("PATCH", "PUT") and "/files/" in uri:
                try:
                    text = body.decode() if isinstance(body, (bytes, bytearray)) else str(body)
                except Exception:
                    text = ""
                if '"trashed"' in text and "true" in text.lower():
                    self._refuse(method, uri, "Drive files.update setting trashed=true")

        # ── Docs / Sheets / Calendar ───────────────────────────────
        # Calendar is read-only by scope. Docs and Sheets have no delete-file
        # endpoints in their own APIs (file deletion goes through Drive, which
        # is blocked above). Content edits within a Doc/Sheet are allowed.

    def _refuse(self, method: str, uri: str, reason: str) -> None:
        raise RuntimeError(
            f"Hermes refused {method} {uri}\n"
            f"Reason: {reason}.\n"
            "Per SAFETY.md, Hermes never sends mail and never deletes files. "
            "To add a destructive operation, gate it through "
            "hermes.policy.require_double_confirm() and update SAFETY.md."
        )


def safe_authorized_http() -> AuthorizedHttp:
    """Use this in every googleapiclient.build() call across hermes.app.google."""
    return AuthorizedHttp(get_credentials(), http=GoogleSafeHttp())
