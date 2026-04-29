"""FastAPI web UI for Hermes.

Bound to 127.0.0.1:8080 only. External traffic arrives via Cloudflare
Tunnel after passing Cloudflare Access (email allowlist enforced at edge).
This service additionally re-validates the CF Access email header — see
auth.py — so even a misconfigured tunnel cannot bypass.

Routes:
  GET  /                         status dashboard
  GET  /linkedin                 secondary cookie status + refresh request
  POST /linkedin/refresh-request notify operator that re-login is needed
  GET  /drafts                   pending drafts (fallback if Telegram is down)
  POST /drafts/{id}/approve      approve a pending draft
  POST /drafts/{id}/discard      discard a pending draft
  GET  /logs                     recent daemon + bot log tail
  GET  /healthz                  no-auth liveness probe (cloudflared health checks)
  GET  /connect/google           STUB — wired up in Phase 4
  GET  /connect/slack            STUB — wired up in Phase 4
  GET  /oauth/google/callback    STUB — wired up in Phase 4
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import llm, notify, profiles, state
from ..config import HERMES_HOME, PROMPTS_DIR
from .auth import require_user

log = logging.getLogger("hermes.web")

WEB_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
LOGS_DIR = HERMES_HOME / "logs"

app = FastAPI(title="Hermes", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


# ─────────────────────── liveness ───────────────────────

@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


# ─────────────────────── status dashboard ───────────────────────

def _status_rows() -> list[dict[str, Any]]:
    """Each row: {name, status: 'ok'|'warn'|'fail', detail}."""
    rows: list[dict[str, Any]] = []

    def _add(name: str, st: str, detail: str) -> None:
        rows.append({"name": name, "status": st, "detail": detail})

    # Codex (primary brain)
    try:
        llm.run(PROMPTS_DIR / "triage.md", "ping", expect_json=False,
                timeout=20, backend="codex")
        _add("Codex (primary)", "ok", "responsive")
    except Exception as e:
        _add("Codex (primary)", "fail", str(e)[:80])

    # Claude (tool)
    try:
        llm.run(PROMPTS_DIR / "triage.md", "ping", expect_json=False,
                timeout=20, backend="claude")
        _add("Claude (tool)", "ok", "responsive")
    except Exception as e:
        _add("Claude (tool)", "warn", str(e)[:80])

    # Google
    try:
        from ..google.auth import get_credentials
        get_credentials()
        _add("Google OAuth", "ok", "valid")
    except Exception as e:
        _add("Google OAuth", "fail", str(e)[:80])

    # Slack
    try:
        from ..slack.auth import bot_client
        bot_client().auth_test()
        _add("Slack", "ok", "tokens valid")
    except Exception as e:
        _add("Slack", "warn", str(e)[:80])

    # Telegram
    primary = os.environ.get("TELEGRAM_PRIMARY_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
    authorized = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").count(",") + 1
    if primary:
        _add("Telegram", "ok", f"primary set, {authorized} authorized")
    else:
        _add("Telegram", "fail", "TELEGRAM_PRIMARY_CHAT_ID not set")

    # Granola
    if os.environ.get("GRANOLA_API_KEY"):
        last = state.kv_get("granola_last_check", "0")
        _add("Granola", "ok",
             "last poll: " + (_fmt_ts(int(last)) if last and last != "0" else "never"))
    else:
        _add("Granola", "warn", "GRANOLA_API_KEY not set")

    # LinkedIn cookies
    cookies_path = HERMES_HOME / "secrets" / "linkedin_secondary_cookies.json"
    if cookies_path.exists():
        age_h = (dt.datetime.now().timestamp() - cookies_path.stat().st_mtime) / 3600
        st = "ok" if age_h < 14 * 24 else "warn"
        _add("LinkedIn cookies", st, f"age {age_h:.0f}h")
    else:
        _add("LinkedIn cookies", "warn", "not yet seeded — run linkedin-cookies setup")

    # Backups
    last_backup = state.kv_get("backup_last_run_ts", "0")
    if last_backup and last_backup != "0":
        age_h = (dt.datetime.now().timestamp() - int(last_backup)) / 3600
        st = "ok" if age_h < 16 else "warn"
        _add("Backups (Drive)", st, f"last: {age_h:.1f}h ago")
    else:
        _add("Backups (Drive)", "warn", "no backup run yet")

    # Approval counter / posture
    posture = state.kv_get("posture", "conservative")
    approvals = state.kv_get("draft_approvals_count", "0")
    _add("Posture", "ok", f"{posture} ({approvals} drafts approved)")

    return rows


@app.get("/", response_class=HTMLResponse)
async def status_page(request: Request, user: str = Depends(require_user)):
    rows = _status_rows()
    return templates.TemplateResponse("status.html", {
        "request": request, "user": user, "rows": rows,
    })


# ─────────────────────── LinkedIn ───────────────────────

@app.get("/linkedin", response_class=HTMLResponse)
async def linkedin_page(request: Request, user: str = Depends(require_user)):
    cookies_path = HERMES_HOME / "secrets" / "linkedin_secondary_cookies.json"
    cookie_age_h = None
    if cookies_path.exists():
        cookie_age_h = (dt.datetime.now().timestamp() - cookies_path.stat().st_mtime) / 3600

    importance = profiles.Importance.load() if hasattr(profiles, "Importance") else None
    # importance.yaml watched_people
    from ..config import Importance
    imp = Importance.load()
    watched = imp.raw.get("linkedin", {}).get("watched_people", []) or []

    last_run_date = state.kv_get("linkedin_last_run_date", "")
    last_run_slot = state.kv_get("linkedin_last_run_slot", "")

    return templates.TemplateResponse("linkedin.html", {
        "request": request, "user": user,
        "cookie_age_h": cookie_age_h,
        "watched": watched,
        "last_run_date": last_run_date,
        "last_run_slot": last_run_slot,
    })


@app.post("/linkedin/refresh-request")
async def linkedin_refresh_request(user: str = Depends(require_user)):
    """She taps a button asking the operator to re-seed LinkedIn cookies."""
    notify.send_text(
        f"⚠️ *LinkedIn cookie refresh requested* (by {user})\n\n"
        "Please SSH to the droplet and run:\n"
        "`sudo -u hermes /opt/hermes/.venv/bin/python -m app.oauth_setup linkedin-cookies`\n\n"
        "Then tap the secondary account through the Playwright window.",
        urgent=True, kind="system", audience="all",
    )
    return RedirectResponse("/linkedin", status_code=303)


# ─────────────────────── pending drafts ───────────────────────

@app.get("/drafts", response_class=HTMLResponse)
async def drafts_page(request: Request, user: str = Depends(require_user)):
    from ..state import conn
    with conn() as c:
        rows = c.execute(
            "SELECT id, source, thread_id, body, payload_json, created_at, status "
            "FROM pending_drafts WHERE status='pending' "
            "ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    drafts = [dict(r) for r in rows]
    for d in drafts:
        d["age_min"] = (dt.datetime.now().timestamp() - d["created_at"]) / 60
    return templates.TemplateResponse("drafts.html", {
        "request": request, "user": user, "drafts": drafts,
    })


@app.post("/drafts/{draft_id}/approve")
async def drafts_approve(draft_id: int, user: str = Depends(require_user)):
    d = state.get_pending_draft(draft_id)
    if not d:
        raise HTTPException(404, "draft not found")
    try:
        if d["source"] == "gmail":
            from ..google import gmail
            gmail.create_draft(d["thread_id"], d["payload"]["in_reply_to"], d["body"])
        elif d["source"] == "gmail_new":
            from ..google import gmail
            gmail.create_fresh_draft(
                to=d["payload"].get("to", ""),
                subject=d["payload"].get("subject", ""),
                body_text=d["body"],
            )
        elif d["source"] == "slack":
            from ..slack import actions as slack_actions
            slack_actions.post_as_her(d["payload"]["channel"], d["body"],
                                      thread_ts=d["payload"].get("thread_ts"))
        else:
            raise HTTPException(400, f"unknown source: {d['source']}")
        state.update_draft_status(draft_id, "approved")
        # Capture as voice sample
        try:
            profiles.capture_voice_sample(
                context=d["payload"].get("voice_context", "default"),
                body=d["body"],
                recipient_email=d["payload"].get("recipient_email", ""),
                source="approved-draft",
            )
        except Exception:
            log.exception("voice capture failed (non-fatal)")
    except Exception as e:
        log.exception("approve failed")
        raise HTTPException(500, f"approve failed: {e}")
    return RedirectResponse("/drafts", status_code=303)


@app.post("/drafts/{draft_id}/discard")
async def drafts_discard(draft_id: int, user: str = Depends(require_user)):
    state.update_draft_status(draft_id, "discarded")
    return RedirectResponse("/drafts", status_code=303)


# ─────────────────────── logs ───────────────────────

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, user: str = Depends(require_user)):
    files = ["daemon.err.log", "daemon.out.log", "bot.err.log",
             "bot.out.log", "web.err.log"]
    out: dict[str, str] = {}
    for fname in files:
        p = LOGS_DIR / fname
        if p.exists():
            out[fname] = _tail(p, 60)
        else:
            out[fname] = "(no log yet)"
    return templates.TemplateResponse("logs.html", {
        "request": request, "user": user, "logs": out,
    })


def _tail(path: Path, n: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n * 200))
            chunk = f.read().decode("utf-8", errors="replace")
        return "\n".join(chunk.splitlines()[-n:])
    except Exception as e:
        return f"(error reading log: {e})"


# ─────────────────────── OAuth (stubs — Phase 4) ───────────────────────

@app.get("/connect/google", response_class=HTMLResponse)
async def connect_google(request: Request, user: str = Depends(require_user)):
    return templates.TemplateResponse("placeholder.html", {
        "request": request, "user": user,
        "title": "Google OAuth",
        "body": (
            "Phase 4 wires up the web-app OAuth flow. Right now Google "
            "OAuth is bootstrapped via "
            "<code>python -m app.oauth_setup google</code> on the droplet "
            "(localhost flow). Once Phase 4 lands, this button will start "
            "the Web Application OAuth flow against a public callback URL."
        ),
    })


@app.get("/connect/slack", response_class=HTMLResponse)
async def connect_slack(request: Request, user: str = Depends(require_user)):
    return templates.TemplateResponse("placeholder.html", {
        "request": request, "user": user,
        "title": "Slack install",
        "body": (
            "Slack tokens are loaded from <code>.env</code>. To rotate, "
            "re-install the app at api.slack.com/apps and update "
            "<code>SLACK_BOT_TOKEN</code> / <code>SLACK_USER_TOKEN</code> / "
            "<code>SLACK_APP_TOKEN</code>. Phase 4 will add a one-tap "
            "install link here."
        ),
    })


# ─────────────────────── helpers ───────────────────────

def _fmt_ts(ts: int) -> str:
    if not ts:
        return "(never)"
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
