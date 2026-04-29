"""/fill-spreadsheet skill.

Two phases:
  1. Recipe registration (first time on a sheet):
       Hermes reads the headers, asks Nikki via Telegram to specify how
       each column should be filled (free-text, e.g. "col B = Apollo
       headcount, col C = most recent funding round from web"). Saves
       to profiles/spreadsheets/<sheet_id>.md and the recipe row.
  2. Run (subsequent calls or after recipe approved):
       For each data row (skipping header), Hermes:
         - Reads column A as the key
         - Gathers data from configured sources (Apollo, SFDC, web research)
         - Calls claude -p with the recipe + headers + available data
         - Writes the row back to the sheet via Sheets API.

The sources (Apollo, SFDC, research) are stub-backed in v1 — when those
modules are implemented, this skill picks them up automatically.

Telegram entrypoints:
  /fill <sheet_url>                — start a run; if no recipe, prompts setup
  /recipe <sheet_url>              — view/edit the saved recipe
  /recipe <sheet_url> set <text>   — replace recipe (free-form text)
"""
from __future__ import annotations

import logging
import re
from typing import Any

from . import apollo, llm, profiles, research, salesforce
from .config import PROMPTS_DIR
from .google import sheets

log = logging.getLogger("hermes.fill_spreadsheet")

PROMPT = PROMPTS_DIR / "fill_spreadsheet.md"

SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def parse_sheet_id(url_or_id: str) -> str | None:
    """Accepts either a full URL or a bare id."""
    s = url_or_id.strip()
    m = SHEET_ID_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9-_]{20,}", s):
        return s
    return None


def get_or_init_recipe(sheet_id: str) -> dict[str, Any] | None:
    """If a recipe exists, return it. Otherwise return None (caller asks Nikki)."""
    return profiles.get_recipe(sheet_id)


def save_recipe(sheet_id: str, instructions: str) -> None:
    meta = sheets.get_metadata(sheet_id)
    profiles.save_recipe(sheet_id, title=meta.get("title", ""),
                         instructions=instructions, last_outcome="")


def _gather_for_row(key: str, recipe_text: str) -> dict[str, Any]:
    """Best-effort source gathering. Each section is a string blob keyed by
    source name; missing sources omit their key.
    """
    out: dict[str, Any] = {}

    # Heuristic: if the key looks like a domain or contains '.', treat as
    # account; otherwise treat as person/company name.
    looks_like_domain = "." in key and " " not in key

    try:
        if looks_like_domain:
            apollo_blob = apollo.enrich_company(key)  # stub; returns {} if not impl
        else:
            apollo_blob = apollo.search_people({"name": key})
        if apollo_blob:
            out["apollo"] = apollo_blob
    except (AttributeError, NotImplementedError):
        pass
    except Exception:
        log.exception("apollo enrichment failed for %s", key)

    try:
        sf_blob = salesforce.lookup_account(key)
        if sf_blob:
            out["salesforce"] = sf_blob
    except (AttributeError, NotImplementedError):
        pass
    except Exception:
        log.exception("salesforce lookup failed for %s", key)

    try:
        if looks_like_domain:
            web_blob = research.extract_company_overview(key)
            if web_blob:
                out["web_research"] = web_blob
    except (AttributeError, NotImplementedError):
        pass
    except Exception:
        log.exception("research failed for %s", key)

    return out


def _llm_fill_row(*, key: str, headers: list[str], recipe_text: str,
                  available: dict[str, Any]) -> dict[str, Any]:
    payload = (
        f"RECIPE:\n{recipe_text}\n\n"
        f"HEADERS:\n{headers}\n\n"
        f"KEY (column A value):\n{key}\n\n"
        f"AVAILABLE DATA:\n{available}\n"
    )
    result = llm.run(PROMPT, payload, expect_json=True, timeout=60)
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected fill response: {type(result)}")
    return result


def run_for_sheet(sheet_id: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Process every data row. Returns a summary dict with counts + per-row notes."""
    recipe = get_or_init_recipe(sheet_id)
    if not recipe:
        return {"status": "needs_recipe",
                "message": "No recipe saved for this sheet. "
                           "Send `/recipe <sheet_url> set <instructions>` first."}

    meta = sheets.get_metadata(sheet_id)
    title = meta.get("title", "")
    tabs = meta.get("tabs", [])
    if not tabs:
        return {"status": "failed", "message": "sheet has no tabs"}
    primary_tab = tabs[0]

    # Read headers + data.
    grid = sheets.read_range(sheet_id, f"{primary_tab}!A1:ZZ500")
    if not grid:
        return {"status": "empty", "message": "sheet is empty"}
    headers = grid[0]
    data_rows = grid[1:]

    summary = {"status": "ok", "title": title, "rows_processed": 0,
               "rows_written": 0, "notes": []}

    for i, row in enumerate(data_rows, start=2):  # +1 for header, +1 for 1-based
        if not row or not (row[0] or "").strip():
            continue
        key = row[0]
        try:
            available = _gather_for_row(key, recipe["instructions"])
            filled = _llm_fill_row(
                key=key, headers=headers,
                recipe_text=recipe["instructions"], available=available,
            )
        except Exception as e:
            log.exception("row %s failed", key)
            summary["notes"].append(f"row {i} ({key}): error: {e}")
            continue

        summary["rows_processed"] += 1
        values = filled.get("values") or []
        if len(values) != len(headers):
            summary["notes"].append(
                f"row {i} ({key}): model returned {len(values)} cells, expected {len(headers)}; skipping"
            )
            continue
        # Preserve key column (col A): never overwrite.
        values[0] = row[0]
        if not dry_run:
            sheets.write_range(sheet_id, f"{primary_tab}!A{i}:{_col_letter(len(values))}{i}",
                               [values])
            summary["rows_written"] += 1
        if filled.get("notes"):
            summary["notes"].append(f"row {i} ({key}): {filled['notes']}")

    profiles.save_recipe(sheet_id, title=title,
                         instructions=recipe["instructions"],
                         last_outcome=f"{summary['rows_written']}/{summary['rows_processed']} written")
    return summary


def _col_letter(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, …"""
    out = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out
