"""Docs — STUB. NOT scoped in v1.

To enable, add `https://www.googleapis.com/auth/documents` (read+write) or
`documents.readonly` to SCOPES in app/google/auth.py and re-run
`python -m app.oauth_setup google`. Pair with drive.file so Hermes can only
modify Docs it created.

Wire up in v2 (research briefs, meeting recaps, account plans).

Planned surface:
    create(title: str, *, parent_folder_id: str | None = None) -> DocMeta
    append_markdown(doc_id: str, md: str) -> None
    read_text(doc_id: str) -> str
    insert_table(doc_id: str, rows: list[list[str]]) -> None

Design notes:
- Markdown → Docs requests is non-trivial. Start with plain paragraphs + bold/italic
  via the batchUpdate ranges API. Lift to a real markdown renderer only when needed.
- For "append a research brief", consider just creating a new Doc each time and
  linking it from the morning briefing — simpler than mutating long-lived docs.
"""
