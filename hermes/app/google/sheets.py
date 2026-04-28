"""Sheets — STUB. NOT scoped in v1.

To enable, add `https://www.googleapis.com/auth/spreadsheets` (read+write) or
`spreadsheets.readonly` to SCOPES in app/google/auth.py and re-run
`python -m app.oauth_setup google`.

The "compare data across a few sources to fill out something" workflow lives here.

Planned surface:
    open(spreadsheet_id: str) -> Spreadsheet
    read_range(sheet_id: str, a1: str) -> list[list[str]]
    write_range(sheet_id: str, a1: str, values: list[list[str]]) -> None
    append_row(sheet_id: str, tab: str, row: list[str]) -> None
    fill_template(sheet_id: str, tab: str, mapping: dict[str, str]) -> None

Design notes:
- For "fill out this spreadsheet by reading these sources", the best UX is a
  Claude Code slash command (`/fill-spreadsheet`) that takes a sheet URL +
  source URLs/files, runs research per row, writes back. Keep this module thin
  and let the slash command compose it.
"""
