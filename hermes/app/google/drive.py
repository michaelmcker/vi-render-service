"""Drive — read existing files, write Hermes-owned files.

Scope: drive.readonly (read all) + drive.file (write only Hermes-created
files). The HTTP transport (_safety.GoogleSafeHttp) blocks all delete and
trash operations regardless of scope.

Surface (v1):
    find_folder(name, parent_id=None) -> folder_id | None
    create_folder(name, parent_id=None) -> folder_id
    ensure_folder(name, parent_id=None) -> folder_id  (find or create)
    upload_file(local_path, name=None, parent_id=None, mime_type=None) -> file_id
    list_in_folder(folder_id) -> list[dict]
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from ._safety import safe_authorized_http

log = logging.getLogger("hermes.drive")

FOLDER_MIME = "application/vnd.google-apps.folder"


def _client():
    return build("drive", "v3", http=safe_authorized_http(), cache_discovery=False)


def find_folder(name: str, *, parent_id: str | None = None) -> str | None:
    """Returns the folder id if a folder with this name exists, else None."""
    q = (
        f"name = '{_escape(name)}' and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = _client().files().list(q=q, fields="files(id,name)", pageSize=10).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def create_folder(name: str, *, parent_id: str | None = None) -> str:
    body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    res = _client().files().create(body=body, fields="id").execute()
    log.info("created Drive folder %s (parent=%s) -> %s", name, parent_id, res["id"])
    return res["id"]


def ensure_folder(name: str, *, parent_id: str | None = None) -> str:
    """find_folder + create_folder if missing. Returns the folder id."""
    existing = find_folder(name, parent_id=parent_id)
    if existing:
        return existing
    return create_folder(name, parent_id=parent_id)


def upload_file(local_path: Path, *, name: str | None = None,
                parent_id: str | None = None, mime_type: str | None = None) -> str:
    """Upload a local file to Drive. Returns the new file id."""
    local_path = Path(local_path)
    body: dict[str, Any] = {"name": name or local_path.name}
    if parent_id:
        body["parents"] = [parent_id]
    if not mime_type:
        guessed, _ = mimetypes.guess_type(str(local_path))
        mime_type = guessed or "application/octet-stream"
    media = MediaFileUpload(str(local_path), mimetype=mime_type, resumable=False)
    res = _client().files().create(body=body, media_body=media, fields="id,name").execute()
    log.info("uploaded %s -> Drive %s", local_path.name, res["id"])
    return res["id"]


def list_in_folder(folder_id: str) -> list[dict[str, Any]]:
    res = _client().files().list(
        q=f"'{folder_id}' in parents and trashed = false",
        fields="files(id,name,mimeType,modifiedTime,size)",
        pageSize=100, orderBy="modifiedTime desc",
    ).execute()
    return res.get("files", [])


def web_view_link(file_id: str) -> str:
    res = _client().files().get(fileId=file_id, fields="webViewLink").execute()
    return res.get("webViewLink", "")


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")
