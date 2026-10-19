"""Backup and restore (FR-14, BUILD_PLAN §8.12).

A backup is one zip: the database (via SQLite's online backup API, safe while the app runs),
every stored PDF and raw response, and a manifest with the schema version.
"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from papertrail import __version__
from papertrail.config import Settings
from papertrail.db.connection import (
    SchemaTooNewError,
    backup_database,
    connect,
    latest_version,
    migrate,
    schema_version,
)
from papertrail.store import new_id

MANIFEST = "manifest.json"
DB_NAME = "papertrail.db"
_ALLOWED = re.compile(
    r"^(papertrail\.db|manifest\.json|files/[0-9a-f]{64}\.pdf|runs/[0-9a-f-]{36}\.json)$"
)


class RestoreError(RuntimeError):
    pass


def create_backup(settings: Settings, out_path: Path, *, created_at: str) -> Path:
    settings.ensure_dirs()
    snapshot = settings.tmp_dir / f"backup-{new_id()}.db"
    conn = connect(settings.db_path)
    try:
        migrate(conn, settings.db_path)
        version = schema_version(conn)
        backup_database(conn, snapshot)
    finally:
        conn.close()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest = {
                "app_version": __version__,
                "schema_version": version,
                "created_at": created_at,
            }
            archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
            archive.write(snapshot, DB_NAME)
            for folder in (settings.files_dir, settings.runs_dir):
                for path in sorted(folder.glob("*")):
                    if path.is_file():
                        archive.write(path, f"{folder.name}/{path.name}")
    finally:
        snapshot.unlink(missing_ok=True)
    return out_path


def _is_empty(settings: Settings) -> bool:
    if settings.db_path.exists():
        return False
    return not any(
        folder.is_dir() and any(folder.iterdir())
        for folder in (settings.files_dir, settings.runs_dir)
    )


def restore_backup(settings: Settings, archive_path: Path) -> int:
    """Restore into an empty data folder. Returns the schema version restored."""
    if not _is_empty(settings):
        raise RestoreError(
            f"The data folder {settings.data_dir} isn't empty. Restore into a new folder "
            "(set PAPERTRAIL_DATA_DIR) or move the current data away first."
        )
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if MANIFEST not in names or DB_NAME not in names:
            raise RestoreError("This file isn't a PaperTrail backup.")
        bad = [n for n in names if not _ALLOWED.match(n)]
        if bad:
            raise RestoreError(f"Unexpected file in backup: {bad[0]}")
        manifest = json.loads(archive.read(MANIFEST))
        version = int(manifest.get("schema_version", 0))
        if version > latest_version():
            raise SchemaTooNewError(
                f"This backup uses schema version {version}; upgrade PaperTrail to restore it."
            )
        settings.ensure_dirs()
        for name in names:
            if name == MANIFEST:
                continue
            target = settings.data_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
    conn = connect(settings.db_path)
    try:
        migrate(conn, settings.db_path)
    finally:
        conn.close()
    return version
