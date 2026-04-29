"""Sheets — read + write.

Scoped via `spreadsheets` (full). Hermes can read and write any Sheet Nikki
has access to. Used by the cross-source spreadsheet-fill workflow.

Surface (v1):
    read_range(sheet_id, a1_range)         -> list[list[str]]
    write_range(sheet_id, a1_range, values) -> None
    append_row(sheet_id, tab, row)          -> None
    get_metadata(sheet_id)                  -> dict (title, tabs, ranges)

A1 notation examples:
    'Sheet1!A1:D10'       a rectangular range on the Sheet1 tab
    'Sheet1!A:A'          all of column A
    'Pipeline'            implicit — entire 'Pipeline' tab
"""
from __future__ import annotations

import logging
from typing import Any

from googleapiclient.discovery import build

from ._safety import safe_authorized_http

log = logging.getLogger("hermes.sheets")


def _client():
    return build("sheets", "v4", http=safe_authorized_http(), cache_discovery=False)


def get_metadata(sheet_id: str) -> dict[str, Any]:
    """Title plus list of tab names. Cheap call — fetch before reads to confirm tabs."""
    res = _client().spreadsheets().get(
        spreadsheetId=sheet_id, fields="properties.title,sheets.properties"
    ).execute()
    tabs = [s["properties"]["title"] for s in res.get("sheets", [])]
    return {"title": res.get("properties", {}).get("title", ""), "tabs": tabs}


def read_range(sheet_id: str, a1: str) -> list[list[str]]:
    """Returns a rectangular array of strings. Empty trailing cells are omitted by the API."""
    res = _client().spreadsheets().values().get(
        spreadsheetId=sheet_id, range=a1, valueRenderOption="UNFORMATTED_VALUE",
    ).execute()
    return [[str(c) for c in row] for row in res.get("values", [])]


def write_range(sheet_id: str, a1: str, values: list[list[Any]]) -> None:
    """Overwrites the cells in `a1` with `values`. USER_ENTERED parses formulas/dates."""
    _client().spreadsheets().values().update(
        spreadsheetId=sheet_id, range=a1, valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    log.info("wrote %dx%d to %s!%s", len(values), len(values[0]) if values else 0, sheet_id, a1)


def append_row(sheet_id: str, tab: str, row: list[Any]) -> None:
    """Appends one row at the bottom of the named tab."""
    _client().spreadsheets().values().append(
        spreadsheetId=sheet_id, range=f"{tab}!A:A",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
