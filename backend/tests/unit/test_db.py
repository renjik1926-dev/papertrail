"""Migrations and the repository (BUILD_PLAN §7, §11)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from papertrail.db import repo
from papertrail.db.connection import (
    MigrationError,
    SchemaTooNewError,
    bundled_migrations,
    connect,
    migrate,
    migrations_from,
    schema_version,
)

NOW = "2026-10-19T15:00:00Z"


def test_empty_database_migrates_to_latest(tmp_path: Path) -> None:
    db = tmp_path / "papertrail.db"
    conn = connect(db)
    report = migrate(conn, db)
    assert schema_version(conn) == len(bundled_migrations()) == report.to_version
    assert report.backup_path is None  # nothing to back up yet
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "documents",
        "pages",
        "blocks",
        "words",
        "runs",
        "items",
        "checks",
        "reviews",
        "jobs",
        "settings",
    } <= tables


def test_pragmas(tmp_path: Path) -> None:
    conn = connect(tmp_path / "x.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def write_migrations(folder: Path, *sql: str) -> None:
    folder.mkdir()
    for number, text in enumerate(sql, start=1):
        (folder / f"{number:04d}_step.sql").write_text(text, encoding="utf-8")


def test_backup_is_written_before_migrating(tmp_path: Path) -> None:
    folder = tmp_path / "migrations"
    write_migrations(folder, "CREATE TABLE a (x INTEGER);", "CREATE TABLE b (y INTEGER);")
    db = tmp_path / "papertrail.db"
    conn = connect(db)
    migrate(conn, db, migrations_from(folder)[:1])
    conn.execute("INSERT INTO a VALUES (1)")
    report = migrate(conn, db, migrations_from(folder))
    assert report.backup_path == tmp_path / "papertrail.db.bak-v1"
    backup = sqlite3.connect(report.backup_path)
    assert backup.execute("SELECT x FROM a").fetchall() == [(1,)]
    assert backup.execute("PRAGMA user_version").fetchone()[0] == 1


def test_failed_migration_rolls_back_and_points_to_backup(tmp_path: Path) -> None:
    folder = tmp_path / "migrations"
    write_migrations(
        folder, "CREATE TABLE a (x INTEGER);", "CREATE TABLE b (y INTEGER); NOT VALID SQL;"
    )
    db = tmp_path / "papertrail.db"
    conn = connect(db)
    migrate(conn, db, migrations_from(folder)[:1])
    with pytest.raises(MigrationError, match=r"bak-v1"):
        migrate(conn, db, migrations_from(folder))
    assert schema_version(conn) == 1
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'b'").fetchone() is None


def test_newer_database_is_refused(tmp_path: Path) -> None:
    db = tmp_path / "papertrail.db"
    conn = connect(db)
    conn.execute("PRAGMA user_version = 99")
    with pytest.raises(SchemaTooNewError, match="Upgrade PaperTrail"):
        migrate(conn, db)


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    db = tmp_path / "papertrail.db"
    connection = connect(db)
    migrate(connection, db)
    return connection


def test_one_active_job_per_document(conn: sqlite3.Connection) -> None:
    repo.insert_document(conn, id="d1", sha256="a" * 64, filename="a.pdf", now=NOW)
    repo.insert_job(conn, id="j1", document_id="d1", now=NOW)
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_job(conn, id="j2", document_id="d1", now=NOW)
    repo.finish_job(conn, "j1", status="done", last_error=None, now=NOW)
    repo.insert_job(conn, id="j3", document_id="d1", now=NOW)


def test_claim_oldest_job_and_recover(conn: sqlite3.Connection) -> None:
    for n in (1, 2):
        repo.insert_document(conn, id=f"d{n}", sha256=str(n) * 64, filename="x.pdf", now=NOW)
        repo.insert_job(conn, id=f"j{n}", document_id=f"d{n}", now=f"2026-10-19T15:00:0{n}Z")
    job = repo.claim_next_job(conn, NOW)
    assert (
        job is not None
        and job["id"] == "j1"
        and job["attempts"] == 1
        and job["status"] == "running"
    )
    assert repo.requeue_running(conn, NOW) == 1
    assert repo.get_job(conn, "j1")["status"] == "queued"  # type: ignore[index]


def test_delete_cascades(conn: sqlite3.Connection) -> None:
    repo.insert_document(conn, id="d1", sha256="a" * 64, filename="a.pdf", now=NOW)
    repo.insert_job(conn, id="j1", document_id="d1", now=NOW)
    repo.insert_run(
        conn,
        id="r1",
        document_id="d1",
        provider="fake",
        model="m",
        prompt_version="v",
        effort="low",
        request_hash="h",
        started_at=NOW,
    )
    repo.delete_document(conn, "d1")
    assert repo.table_counts(conn, ["documents", "jobs", "runs"]) == {
        "documents": 0,
        "jobs": 0,
        "runs": 0,
    }


def test_settings_upsert(conn: sqlite3.Connection) -> None:
    repo.put_setting(conn, "privacy_notice_ack", "true")
    repo.put_setting(conn, "privacy_notice_ack", "false")
    assert repo.get_settings(conn) == {"privacy_notice_ack": "false"}


def test_item_updates_only_allow_editable_fields(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="not editable"):
        repo.update_item_fields(conn, "i1", review_state="edited", fields={"quote": "x"})
