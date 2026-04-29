---
description: Produce a one-page research brief on a prospective account
argument-hint: <domain>
---

# Research account: $1

You are running inside Nikki's Hermes workspace at `~/hermes`. Use these tools:

1. **Apollo enrichment** — call `python -m app.cli apollo-enrich $1` to get
   firmographics + top contacts.
2. **Salesforce snapshot** — call `python -m app.cli sf-account $1` to see if
   we have an existing account, recent activity, and current stage.
3. **Web research** — call `python -m app.cli research $1` for homepage +
   recent news.

Synthesize using the prompt at `prompts/research_brief.md`. Save the output to
`~/hermes/output/research/$1-{date}.md`.

If Drive scopes are wired up later, also create a Google Doc and surface the
link in the morning briefing.
