"""Hermes daemon — the always-on watcher.

What runs:
  1. Slack Socket Mode listener (background thread; events delivered as they occur).
  2. Gmail polling loop (every HERMES_GMAIL_POLL_SECONDS).
  3. Slack DM polling loop (every HERMES_DM_POLL_SECONDS).
  4. Daily morning briefing at the configured time.

The Telegram BOT runs in a SEPARATE launchd job (com.vi.hermes.bot.plist) —
keeping the watcher and bot decoupled means a buggy handler can't take down
the watcher and vice versa.
"""
from __future__ import annotations

import datetime as dt
import logging
import time
import zoneinfo

from . import classify, notify, state
from .config import Importance, env, env_int
from .google import gmail
from .slack import dms, events

log = logging.getLogger("hermes.daemon")


def _now_in_tz() -> dt.datetime:
    return dt.datetime.now(zoneinfo.ZoneInfo(env("HERMES_TIMEZONE", "America/New_York")))


def gmail_tick() -> None:
    last = int(state.kv_get("gmail_last_check", "0") or "0")
    after = last - 60 if last else int(time.time()) - 3600
    try:
        msgs = gmail.list_unread(after_unix=after, max_results=25)
    except Exception:
        log.exception("gmail fetch failed")
        return

    for msg in msgs:
        if state.already_seen("gmail", msg["id"]):
            continue
        try:
            triage = classify.classify_email(msg)
        except Exception:
            log.exception("triage error for %s", msg["id"])
            continue
        state.mark_seen("gmail", msg["id"], triage["priority"], triage.get("summary", ""))
        if triage["priority"] in ("urgent", "today"):
            notify.alert_email(msg, triage)

    state.kv_set("gmail_last_check", str(int(time.time())))


def slack_dm_tick() -> None:
    try:
        dms.poll_once(on_alert=lambda e: notify.alert_slack(e, e["_triage"]))
    except Exception:
        log.exception("slack DM poll failed")


def briefing_tick() -> None:
    importance = Importance.load()
    target = importance.budget.get("morning_briefing_at", "07:00")
    now = _now_in_tz()
    last_briefing = state.kv_get("last_briefing_date", "")
    today_str = now.date().isoformat()
    if last_briefing == today_str:
        return
    target_h, target_m = (int(x) for x in target.split(":"))
    if (now.hour, now.minute) < (target_h, target_m):
        return

    from .state import conn
    with conn() as c:
        rows = c.execute(
            "SELECT priority, summary FROM seen_messages "
            "WHERE seen_at > strftime('%s','now','-18 hours') "
            "AND priority IN ('today','urgent') "
            "ORDER BY seen_at DESC LIMIT 30"
        ).fetchall()
    items = [{"priority": r["priority"], "summary": r["summary"]} for r in rows]
    notify.daily_briefing(items)
    state.kv_set("last_briefing_date", today_str)


def heartbeat_tick() -> None:
    """Once an hour, log a debug line. Surfaces silent failures via launchd logs."""
    log.info("hermes daemon heartbeat — seen-table healthy")


def run() -> None:
    log.info("Hermes daemon starting")

    # 1. Slack events listener (Socket Mode runs forever in its own thread)
    try:
        events.start(on_alert=lambda e: notify.alert_slack(e, e["_triage"]))
    except Exception:
        log.exception("slack events listener failed to start; continuing without it")

    gmail_interval = env_int("HERMES_GMAIL_POLL_SECONDS", 180)
    dm_interval = env_int("HERMES_DM_POLL_SECONDS", 60)
    last_gmail = 0.0
    last_dm = 0.0
    last_heartbeat = 0.0

    while True:
        now = time.time()
        if now - last_gmail >= gmail_interval:
            gmail_tick()
            last_gmail = now
        if now - last_dm >= dm_interval:
            slack_dm_tick()
            last_dm = now
        briefing_tick()
        if now - last_heartbeat >= 3600:
            heartbeat_tick()
            last_heartbeat = now
        time.sleep(15)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    run()
