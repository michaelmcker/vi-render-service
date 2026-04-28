"""Drive — STUB. NOT scoped in v1.

To enable, add one of these to SCOPES in app/google/auth.py and re-run
`python -m app.oauth_setup google`:

    drive.readonly                     # read everything she has access to
    drive.file                         # only files Hermes itself creates
    drive.readonly + drive.file        # read all + write only Hermes-owned files (recommended)

Recommendation when wiring up: drive.readonly + drive.file. Hermes can read
her existing files for research/context, but can only modify or delete files
it created itself. Her existing Docs, Sheets, etc. cannot be touched.

Planned surface:
    find(query: str) -> list[FileMeta]
    read_text(file_id: str) -> str          # exports Docs to text, fetches plain files
    upload(local_path: Path, *, parent_id: str | None = None) -> FileMeta
    create_folder(name: str, *, parent_id: str | None = None) -> FileMeta
    share(file_id: str, email: str, role: str = "reader") -> None
"""
