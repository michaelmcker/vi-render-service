"""Daily backups to her company Google Drive.

Twice daily (default 7am + 7pm her time, configurable in importance.yaml
budget.backup_times), Hermes packages everything that matters and uploads
a timestamped zip to a "Hermes Backups" folder in her Drive.

Bundle contents:
  - state.sqlite                     (structured memory: people, accounts,
                                      recipes, voice samples, seen messages)
  - profiles/ (recursive)            (narrative people/account/recipe notes)
  - brand/ (recursive)               (icp, product, pricing, network)
  - config/importance.yaml           (live config — VIPs, watchlists, voice)
  - calendar.json                    (next 90 days of events from her primary
                                      calendar — usable to rebuild schedule)

NOT included (sensitive credentials):
  - .env (Slack tokens, Telegram bot token, Apollo key, Buffer token)
  - secrets/google_*.json (OAuth refresh tokens)
  - secrets/linkedin_*.json (secondary-account cookies)

Those live only on the Mac. If the Mac dies, she re-runs OAuth flows on
a new Mac and restores everything else from the latest backup.

Retention: no automatic cleanup (we never delete files). Each backup is a
new timestamped zip. Storage cost is trivial — sqlite + markdown is
typically < 50 MB. After a year of twice-daily backups: ~30 GB at most,
usually far less. She can manually clean the folder once a year if she
cares.

If a backup fails: Telegram ping, retry next slot. If two slots in a row
fail: escalate to urgent.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import notify, state
from .config import HERMES_HOME
from .google import calendar as gcal, drive

log = logging.getLogger("hermes.backup")

DRIVE_FOLDER_NAME = "Hermes Backups"
INCLUDE_DIRS = ["profiles", "brand"]
INCLUDE_FILES = [
    "state.sqlite",
    "config/importance.yaml",
]


def _drive_folder_id() -> str:
    cached = state.kv_get("backup_drive_folder_id", "")
    if cached:
        return cached
    fid = drive.ensure_folder(DRIVE_FOLDER_NAME)
    state.kv_set("backup_drive_folder_id", fid)
    return fid


def _calendar_export_json() -> str:
    """Next 90 days of events as JSON."""
    try:
        events = gcal.upcoming(hours=90 * 24)
    except Exception:
        log.exception("calendar export failed; backing up empty list")
        events = []
    return json.dumps(events, indent=2, default=str)


def _build_zip(zip_path: Path) -> dict[str, int]:
    counts = {"files": 0, "dirs": 0}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in INCLUDE_FILES:
            p = HERMES_HOME / rel
            if p.exists():
                z.write(p, arcname=rel)
                counts["files"] += 1

        for dirname in INCLUDE_DIRS:
            d = HERMES_HOME / dirname
            if not d.exists():
                continue
            counts["dirs"] += 1
            for child in d.rglob("*"):
                if not child.is_file():
                    continue
                # Skip empty .gitkeep files in backups
                if child.name == ".gitkeep":
                    continue
                arcname = child.relative_to(HERMES_HOME)
                z.write(child, arcname=str(arcname))
                counts["files"] += 1

        # Calendar export inline
        z.writestr("calendar.json", _calendar_export_json())
        counts["files"] += 1

        # Manifest with timestamp + counts (helps when restoring)
        manifest = {
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "hermes_home": str(HERMES_HOME),
            "files": counts["files"],
            "dirs_included": INCLUDE_DIRS,
        }
        z.writestr("MANIFEST.json", json.dumps(manifest, indent=2))
        counts["files"] += 1

    return counts


def run_backup() -> dict[str, str]:
    """Build the zip, upload to Drive, return status dict."""
    folder_id = _drive_folder_id()

    stamp = dt.datetime.now().strftime("%Y-%m-%d-%H%M")
    zip_name = f"hermes-backup-{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="hermes-backup-") as tmpdir:
        zip_path = Path(tmpdir) / zip_name
        try:
            counts = _build_zip(zip_path)
        except Exception:
            log.exception("zip build failed")
            return {"status": "failed", "stage": "zip"}

        size_mb = zip_path.stat().st_size / (1024 * 1024)

        try:
            file_id = drive.upload_file(zip_path, parent_id=folder_id,
                                        mime_type="application/zip")
        except Exception:
            log.exception("Drive upload failed")
            return {"status": "failed", "stage": "upload"}

    state.kv_set("backup_last_run_ts", str(int(dt.datetime.now().timestamp())))
    state.kv_set("backup_last_file_id", file_id)
    log.info("backup uploaded: %s (%.1f MB, %d files)", zip_name, size_mb, counts["files"])
    return {"status": "ok", "file_id": file_id, "name": zip_name,
            "size_mb": f"{size_mb:.1f}", "files": str(counts["files"])}


def run_with_failure_tracking() -> dict[str, str]:
    """Wrap run_backup with consecutive-failure escalation."""
    result = run_backup()
    if result.get("status") == "ok":
        state.kv_set("backup_consecutive_failures", "0")
        return result

    fails = int(state.kv_get("backup_consecutive_failures", "0") or "0") + 1
    state.kv_set("backup_consecutive_failures", str(fails))

    msg = f"⚠️ Backup failed at stage `{result.get('stage', '?')}` ({fails} consecutive)."
    if fails >= 2:
        notify.send_text(msg + " Please check logs.", urgent=True,
                         kind="system", audience="all")
    else:
        notify.send_text(msg, urgent=False, kind="system", audience="all")
    return result
