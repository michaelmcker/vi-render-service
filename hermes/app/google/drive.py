"""Drive — scoped in v1 (drive.readonly + drive.file). Surface implemented as needed.

Hermes can read everything Nikki has access to (drive.readonly) but can only
modify/delete files it created itself (drive.file). Her pre-existing Docs,
Sheets, and files are read-only from Hermes's perspective.

Planned surface (implement as workflows need it):
    find(query: str) -> list[FileMeta]
    read_text(file_id: str) -> str          # exports Docs to text, fetches plain files
    create_folder(name: str, *, parent_id: str | None = None) -> FileMeta
    upload(local_path: Path, *, parent_id: str | None = None) -> FileMeta

The Hermes outputs folder ("Hermes — Sales Notes") is created on first write
and its id cached in state.kv as 'hermes_drive_folder_id'.
"""
