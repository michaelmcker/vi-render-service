"""Hermes safety policy — the canonical reference is ../../SAFETY.md.

This module exists to:
  1. Document the policy in code (so reviewers see it during diffs).
  2. Provide require_double_confirm(), the gate any future destructive
     operation must pass through.

Currently NO Hermes operation calls require_double_confirm(). Destructive
operations (send mail, delete files, trash anything) are blocked outright at
the HTTP-transport layer in app/google/_safety.py.

If you find yourself wanting to add a destructive operation:
  1. Update SAFETY.md with the rationale.
  2. Carve a specific exception in app/google/_safety.py.
  3. Wrap the call site with require_double_confirm().
  4. Add an audit log entry to state.notify_log.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass

from . import notify, state

log = logging.getLogger("hermes.policy")

CONFIRM_WINDOW_SECONDS = 300  # confirmation must arrive within 5 minutes


@dataclass
class PendingConfirmation(Exception):
    """Raised when an operation needs confirmation. Caller must abort."""
    action_id: str
    description: str


def require_double_confirm(action_id: str, description: str) -> None:
    """Two-step confirmation gate.

    Call BEFORE executing any destructive operation:
        require_double_confirm(
            action_id=f"send_mail.thread:{thread_id}",
            description=f"Send the drafted reply to {to_addr}?",
        )

    Behaviour:
      - First call: stores a confirmation token in state.kv, sends a Telegram
        message asking Nikki to reply with /confirm <token>, raises
        PendingConfirmation. Caller's operation aborts.
      - Within CONFIRM_WINDOW_SECONDS, if Nikki sends /confirm <token>,
        the bot stores the confirmation in state.kv.
      - Second call (after confirmation): clears the token, returns None,
        caller proceeds.
      - If the confirmation expires or doesn't arrive, the second call
        raises PendingConfirmation again.

    Audit: every confirmed destructive operation is recorded in state.notify_log
    with kind='destructive_confirmed' for after-the-fact review.
    """
    key = f"confirm:{action_id}"
    confirmed_key = f"{key}:confirmed"

    if state.kv_get(confirmed_key):
        # Second call after Nikki confirmed — clear and proceed.
        state.kv_set(confirmed_key, "")
        state.kv_set(key, "")
        state.log_notify("destructive_confirmed")
        log.warning("destructive op CONFIRMED: %s — %s", action_id, description)
        return

    # First call (or expired) — issue a token and ask.
    token = secrets.token_urlsafe(8)
    state.kv_set(key, f"{int(time.time())}:{token}")
    notify.send_text(
        f"⚠️ *Confirmation required*\n\n{description}\n\n"
        f"Reply *exactly*:\n`/confirm {token}`\n\n"
        f"If you do nothing, the action is cancelled in 5 minutes.",
        kind="system",
        urgent=True,
    )
    raise PendingConfirmation(action_id=action_id, description=description)


def accept_confirmation(token: str) -> bool:
    """Called by the Telegram /confirm handler."""
    # Walk all confirm:* keys and find a matching token within window.
    from .state import conn
    now = int(time.time())
    with conn() as c:
        rows = c.execute("SELECT k, v FROM kv WHERE k LIKE 'confirm:%' AND k NOT LIKE '%:confirmed'").fetchall()
    for r in rows:
        try:
            ts_s, tok = r["v"].split(":", 1)
        except (ValueError, AttributeError):
            continue
        if tok == token and now - int(ts_s) <= CONFIRM_WINDOW_SECONDS:
            state.kv_set(f"{r['k']}:confirmed", "1")
            return True
    return False
