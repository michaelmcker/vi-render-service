"""Web research — STUB. Local Playwright (no Browserbase, no API spend).

Used by:
  - The morning briefing for "what's new at <account>" snippets
  - The /research-account Claude Code slash command
  - Apollo enrichment top-up (when Apollo lacks recent news)

Planned surface:
    fetch(url: str, *, render_js: bool = True, timeout: int = 20) -> Page
    search(query: str, *, n: int = 10) -> list[SearchResult]
        # uses a plain Bing/DuckDuckGo HTML scrape; no API key
    extract_company_overview(domain: str) -> CompanyOverview
        # homepage + /about + a couple of news hits, structured

Design notes:
- Headless Chromium via playwright. Install with:
    pip install -e .[research]
    playwright install chromium
- Cache fetched pages in state.kv for 24h — keep traffic polite.
- Time-limit every page (20s) and total research run (90s).
- For Browserbase later: same surface, swap the fetch backend. Don't add
  Browserbase in v1 — it requires an API key.
"""
