"""SQLite state. Tracks seen messages, pending drafts, snoozes, and noise budget.

This is Hermes-local state, never written back to Gmail or Slack.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import STATE_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_messages (
    source       TEXT NOT NULL,        -- 'gmail' | 'slack'
    external_id  TEXT NOT NULL,        -- gmail message id / slack ts+channel
    seen_at      INTEGER NOT NULL,
    priority     TEXT,                 -- triage result
    summary      TEXT,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS pending_drafts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,        -- 'gmail' | 'slack'
    thread_id    TEXT NOT NULL,
    body         TEXT NOT NULL,        -- the draft text
    payload_json TEXT,                 -- extra context (gmail draft id, slack channel, etc.)
    created_at   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending'  -- pending | approved | discarded
);

CREATE TABLE IF NOT EXISTS snoozes (
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    until_ts     INTEGER NOT NULL,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS notify_log (
    ts           INTEGER NOT NULL,
    kind         TEXT NOT NULL         -- 'urgent' | 'briefing' | 'system'
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
"""


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(STATE_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def mark_seen(source: str, external_id: str, priority: str, summary: str) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO seen_messages(source, external_id, seen_at, priority, summary) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, external_id, int(time.time()), priority, summary),
        )


def already_seen(source: str, external_id: str) -> bool:
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM seen_messages WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
    return row is not None


def save_pending_draft(source: str, thread_id: str, body: str, payload: dict[str, Any]) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO pending_drafts(source, thread_id, body, payload_json, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (source, thread_id, body, json.dumps(payload), int(time.time())),
        )
        return cur.lastrowid


def get_pending_draft(draft_id: int) -> dict[str, Any] | None:
    with conn() as c:
        row = c.execute("SELECT * FROM pending_drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d.pop("payload_json") or "{}")
    return d


def update_draft_status(draft_id: int, status: str) -> None:
    with conn() as c:
        c.execute("UPDATE pending_drafts SET status=? WHERE id=?", (status, draft_id))


def snooze(source: str, external_id: str, seconds: int) -> None:
    with conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO snoozes(source, external_id, until_ts) VALUES (?, ?, ?)",
            (source, external_id, int(time.time()) + seconds),
        )


def is_snoozed(source: str, external_id: str) -> bool:
    with conn() as c:
        row = c.execute(
            "SELECT until_ts FROM snoozes WHERE source=? AND external_id=?",
            (source, external_id),
        ).fetchone()
    return bool(row and row["until_ts"] > time.time())


def log_notify(kind: str) -> None:
    with conn() as c:
        c.execute("INSERT INTO notify_log(ts, kind) VALUES (?, ?)", (int(time.time()), kind))


def alerts_in_last_hour() -> int:
    cutoff = int(time.time()) - 3600
    with conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM notify_log WHERE ts > ? AND kind='urgent'", (cutoff,)
        ).fetchone()
    return row["n"]


def kv_get(key: str, default: str | None = None) -> str | None:
    with conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def kv_set(key: str, value: str) -> None:
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO kv(k, v) VALUES (?, ?)", (key, value))
