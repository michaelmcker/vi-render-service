"""Calendar — READ ONLY. Used for morning-briefing context ("you have 4 meetings
today, the 2pm with Acme is the one to prep").

Scope: calendar.readonly. Hermes cannot create, edit, or delete events.

Surface (v1):
    today_events() -> list[Event]
    week_events() -> list[Event]

Each Event has: id, summary, start, end, attendees (emails), is_external,
conference_url. The watcher uses these to enrich the morning briefing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from googleapiclient.discovery import build

from .auth import get_credentials


def _client():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def today_events() -> list[dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=0)
    return _list_events(now, end)


def upcoming(hours: int = 24) -> list[dict[str, Any]]:
    now = dt.datetime.now(dt.timezone.utc)
    return _list_events(now, now + dt.timedelta(hours=hours))


def _list_events(start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
    res = _client().events().list(
        calendarId="primary",
        timeMin=start.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=50,
    ).execute()
    return [_normalize(e) for e in res.get("items", [])]


def _normalize(e: dict[str, Any]) -> dict[str, Any]:
    attendees = [a.get("email", "") for a in e.get("attendees", []) if a.get("email")]
    self_email = next((a.get("email") for a in e.get("attendees", []) if a.get("self")), None)
    external = bool(self_email and any(
        a.split("@")[-1] != self_email.split("@")[-1] for a in attendees if "@" in a
    ))
    return {
        "id": e["id"],
        "summary": e.get("summary", "(no title)"),
        "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
        "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
        "attendees": attendees,
        "is_external": external,
        "conference_url": e.get("hangoutLink") or "",
    }
