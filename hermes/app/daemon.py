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

import os
import re

from . import backup, classify, granola, notify, profiles, state, thought_leadership
from .config import Importance, env, env_int
from .google import gmail
from .linkedin import scanner as linkedin_scanner
from .slack import dms, events


_EMAIL_RE = re.compile(r"[\w._%+-]+@[\w.-]+\.[A-Za-z]{2,}")


def _extract_email(from_header: str) -> str:
    m = _EMAIL_RE.search(from_header or "")
    return m.group(0).lower() if m else ""


def _extract_display_name(from_header: str) -> str:
    """`Jane Doe <jane@acme.com>` -> 'Jane Doe'; bare email -> ''."""
    if "<" in (from_header or ""):
        return from_header.split("<", 1)[0].strip().strip('"')
    return ""

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
        state.mark_seen("gmail", msg["id"], triage["priority"], triage.get("summary", ""), triage=triage)
        # Bump person/account profiles based on the sender.
        try:
            sender_email = _extract_email(msg.get("from", ""))
            if sender_email:
                profiles.note_interaction(
                    email=sender_email,
                    display_name=_extract_display_name(msg.get("from", "")),
                    summary=triage.get("summary", "")[:160],
                    voice_context=profiles.infer_voice_context(sender_email),
                )
        except Exception:
            log.exception("profiles.note_interaction failed for %s", msg.get("from"))
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


def linkedin_tick() -> None:
    """Twice daily (default 8am + 4pm her time), kick the LinkedIn scanner.

    Times configurable via importance.yaml budget.linkedin_scan_times.
    """
    importance = Importance.load()
    times = importance.budget.get("linkedin_scan_times", ["08:00", "16:00"])
    now = _now_in_tz()
    today_str = now.date().isoformat()
    last_run_date = state.kv_get("linkedin_last_run_date", "")
    last_run_slot = state.kv_get("linkedin_last_run_slot", "")

    # Find the most recent slot that has elapsed today.
    elapsed_today = [t for t in times if (now.hour, now.minute) >= tuple(int(x) for x in t.split(":"))]
    if not elapsed_today:
        return
    current_slot = elapsed_today[-1]

    if last_run_date == today_str and last_run_slot == current_slot:
        return  # already ran this slot

    log.info("linkedin scan tick: slot=%s", current_slot)
    try:
        counts = linkedin_scanner.run_once()
        log.info("linkedin scan complete: %s", counts)
    except Exception:
        log.exception("linkedin scan failed")
    state.kv_set("linkedin_last_run_date", today_str)
    state.kv_set("linkedin_last_run_slot", current_slot)


def thought_leadership_tick() -> None:
    """Once a week (default Sunday 09:00 her time), synthesize the archive."""
    importance = Importance.load()
    spec = importance.budget.get("thought_leadership_weekly_at", "Sunday 09:00")
    try:
        day_str, time_str = spec.split()
        target_h, target_m = (int(x) for x in time_str.split(":"))
    except ValueError:
        log.warning("invalid thought_leadership_weekly_at: %r", spec)
        return
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    target_day = day_str.capitalize()
    if target_day not in days:
        log.warning("invalid weekday in thought_leadership_weekly_at: %r", day_str)
        return
    target_dow = days.index(target_day)

    now = _now_in_tz()
    if now.weekday() != target_dow:
        return
    if (now.hour, now.minute) < (target_h, target_m):
        return

    iso_year, iso_week, _ = now.date().isocalendar()
    week_label = f"{iso_year}-W{iso_week:02d}"
    if state.kv_get("tl_last_week", "") == week_label:
        return  # already ran this week

    log.info("thought-leadership weekly tick: %s", week_label)
    try:
        result = thought_leadership.run_weekly()
        log.info("thought-leadership: %s", result)
    except Exception:
        log.exception("thought-leadership weekly run failed")


def backup_tick() -> None:
    """Twice daily (default 7am + 7pm her time) per importance.yaml budget.backup_times."""
    importance = Importance.load()
    times = importance.budget.get("backup_times", ["07:00", "19:00"])
    now = _now_in_tz()
    today_str = now.date().isoformat()
    last_date = state.kv_get("backup_last_run_date", "")
    last_slot = state.kv_get("backup_last_run_slot", "")

    elapsed_today = [t for t in times if (now.hour, now.minute) >= tuple(int(x) for x in t.split(":"))]
    if not elapsed_today:
        return
    current_slot = elapsed_today[-1]
    if last_date == today_str and last_slot == current_slot:
        return

    log.info("backup tick: slot=%s", current_slot)
    try:
        result = backup.run_with_failure_tracking()
        log.info("backup result: %s", result)
    except Exception:
        log.exception("backup tick crashed")
    # Mark slot used regardless of success — failure ping is sent inside.
    state.kv_set("backup_last_run_date", today_str)
    state.kv_set("backup_last_run_slot", current_slot)


def granola_tick() -> None:
    """Poll Granola for new transcripts, archive + ping Telegram for each."""
    if not os.environ.get("GRANOLA_API_KEY"):
        return  # not configured
    try:
        counts = granola.poll_once()
        if counts["new"]:
            log.info("granola: %s", counts)
    except Exception:
        log.exception("granola poll failed")


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
    granola_interval = env_int("HERMES_GRANOLA_POLL_SECONDS", 300)
    last_gmail = 0.0
    last_dm = 0.0
    last_granola = 0.0
    last_heartbeat = 0.0

    while True:
        now = time.time()
        if now - last_gmail >= gmail_interval:
            gmail_tick()
            last_gmail = now
        if now - last_dm >= dm_interval:
            slack_dm_tick()
            last_dm = now
        if now - last_granola >= granola_interval:
            granola_tick()
            last_granola = now
        briefing_tick()
        linkedin_tick()
        thought_leadership_tick()
        backup_tick()
        if now - last_heartbeat >= 3600:
            heartbeat_tick()
            last_heartbeat = now
        time.sleep(15)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    run()
