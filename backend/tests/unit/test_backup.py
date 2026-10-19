"""Backup and restore (FR-14): newer schemas are refused; restored data shows the same items."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from papertrail.backup import RestoreError, create_backup, restore_backup
from papertrail.clock import FixedClock
from papertrail.config import Settings
from papertrail.db.connection import SchemaTooNewError, connect, migrate
from tests.conftest import EVAL_DOCS, make_client, process_all, upload


def test_restored_app_shows_the_same_items(
    settings: Settings, clock: FixedClock, tmp_path: Path
) -> None:
    http, worker = make_client(settings, clock)
    with http:
        doc = upload(http, EVAL_DOCS / "insurance_eob_01.pdf")
        process_all(worker)
        before = http.get(f"/api/documents/{doc['id']}/items").json()
        archive = create_backup(settings, tmp_path / "b.zip", created_at="2026-10-19T00:00:00Z")

    restored = settings.model_copy(update={"data_dir": tmp_path / "restored"})
    assert restore_backup(restored, archive) == 1
    http2, _ = make_client(restored, clock)
    with http2:
        after = http2.get(f"/api/documents/{doc['id']}/items").json()
        assert http2.get(f"/api/documents/{doc['id']}/file").status_code == 200
    assert after == before


def test_backup_while_a_write_transaction_is_open(
    settings: Settings, clock: FixedClock, tmp_path: Path
) -> None:
    settings.ensure_dirs()
    writer = connect(settings.db_path)
    migrate(writer, settings.db_path)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("INSERT INTO settings (key, value) VALUES ('privacy_notice_ack', 'true')")
    archive = create_backup(settings, tmp_path / "b.zip", created_at="now")  # doesn't block or fail
    writer.execute("COMMIT")
    assert zipfile.ZipFile(archive).testzip() is None


def test_newer_backup_is_refused(settings: Settings, tmp_path: Path) -> None:
    archive = tmp_path / "future.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", json.dumps({"schema_version": 99}))
        handle.writestr("papertrail.db", b"")
    with pytest.raises(SchemaTooNewError):
        restore_backup(settings, archive)


def test_unexpected_paths_are_refused(settings: Settings, tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("manifest.json", json.dumps({"schema_version": 1}))
        handle.writestr("papertrail.db", b"")
        handle.writestr("../outside.txt", b"x")
    with pytest.raises(RestoreError, match="Unexpected file"):
        restore_backup(settings, archive)
