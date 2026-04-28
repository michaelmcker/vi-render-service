"""Apollo — STUB. Direct API using Nikki's existing Apollo seat.

API key comes from Apollo > Settings > Integrations > API > Generate, stored
in .env as APOLLO_API_KEY.

Planned surface:
    search_people(query: PeopleQuery) -> list[Person]
        # title in ['VP Sales','Head of RevOps'], industry, headcount,
        # location, technographics, etc.
    enrich_company(domain: str) -> Company
    enrich_person(email: str | linkedin_url: str) -> Person
    add_to_sequence(person_id: str, sequence_id: str) -> None    # write — flag-gated
    list_recent_signals(account_ids: list[str]) -> list[Signal]
        # hiring, funding, exec changes — for the morning briefing

Design notes:
- Apollo's API is REST + JSON. Use httpx with Authorization: 'Cache-Control: no-cache'
  and a custom 'X-Api-Key' header.
- Cache enrichment results in state.kv for 7 days — Apollo charges per credit.
- No write operations (sequences, contacts) until Nikki opts in via a flag.
"""
