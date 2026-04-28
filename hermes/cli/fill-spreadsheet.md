---
description: Fill a comparison spreadsheet by researching across multiple sources
argument-hint: <sheet-url> <source-list-or-prompt>
---

# Fill spreadsheet: $1

The spreadsheet at $1 has a header row and (likely) a list of accounts/people in
column A. Each remaining column is a fact to research.

For each row:
1. Read the row's primary key (column A).
2. Read column headers to know what to fill.
3. Use the appropriate source for each column:
   - "Apollo:*" -> python -m app.cli apollo-enrich
   - "SFDC:*"   -> python -m app.cli sf-account
   - "Web:*"    -> python -m app.cli research
4. Write back with `python -m app.cli sheets-write <sheet-id> <range> <values>`.

Confirm with Nikki before any column that requires sending paid Apollo credits
(enrichment/search). Always show row counts and a preview of cells before
writing.

NOTE: Sheets/Drive OAuth scopes are NOT wired up in v1. Run
`python -m app.oauth_setup google --extend sheets,drive` first to authorize.
