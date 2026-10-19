"""SQLite connections and the migration runner (BUILD_PLAN §7).

Every connection: foreign keys on, WAL journal, 5 s busy timeout (API requests and the
worker wait briefly for each other instead of failing with "database is locked"), and
secure_delete so deleted letters don't linger in free pages.
Connections run in autocommit mode; write transactions are explicit and short.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

MIN_SQLITE = (3, 35, 0)  # UPDATE ... RETURNING
BUSY_TIMEOUT_MS = 5000
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class SchemaTooNewError(RuntimeError):
    """The database was written by a newer PaperTrail."""


class MigrationError(RuntimeError):
    pass


def check_sqlite_version() -> None:
    if sqlite3.sqlite_version_info < MIN_SQLITE:
        found = sqlite3.sqlite_version
        raise RuntimeError(f"PaperTrail needs SQLite 3.35 or newer (found {found}).")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        path, isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT_MS / 1000
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    # Overwrite deleted content, so a deleted letter's text doesn't linger in free pages.
    conn.execute("PRAGMA secure_delete = ON")
    return conn


def checkpoint(conn: sqlite3.Connection) -> None:
    """Fold the WAL back into the database file and empty it (after deleting a document)."""
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = False) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def migrations_from(folder: Traversable) -> list[Migration]:
    found = []
    for entry in folder.iterdir():
        match = _MIGRATION_NAME.match(entry.name)
        if match:
            sql = entry.read_text(encoding="utf-8")
            found.append(Migration(int(match.group(1)), entry.name, sql))
    return _validated(found)


def bundled_migrations() -> list[Migration]:
    return migrations_from(files("papertrail.db") / "migrations")


def _validated(migrations: list[Migration]) -> list[Migration]:
    migrations.sort(key=lambda m: m.version)
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"Migrations must be numbered 0001, 0002, ... (found {migration.name})."
            )
    return migrations


def schema_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def latest_version(migrations: list[Migration] | None = None) -> int:
    return len(migrations if migrations is not None else bundled_migrations())


@dataclass(frozen=True)
class MigrationReport:
    from_version: int
    to_version: int
    backup_path: Path | None


def backup_database(conn: sqlite3.Connection, destination: Path) -> None:
    """SQLite's online backup: safe even with WAL and a running app."""
    target = sqlite3.connect(destination)
    try:
        conn.backup(target)
    finally:
        target.close()


def migrate(
    conn: sqlite3.Connection, db_path: Path, migrations: list[Migration] | None = None
) -> MigrationReport:
    """Apply pending migrations, each in its own transaction, after backing up the file."""
    check_sqlite_version()
    migrations = migrations if migrations is not None else bundled_migrations()
    current = schema_version(conn)
    latest = len(migrations)
    if current > latest:
        raise SchemaTooNewError(
            f"This database uses schema version {current}, but this PaperTrail only knows up to "
            f"{latest}. Upgrade PaperTrail to open it."
        )
    if current == latest:
        return MigrationReport(current, current, None)

    backup_path: Path | None = None
    if current > 0:
        backup_path = db_path.with_name(f"{db_path.name}.bak-v{current}")
        backup_database(conn, backup_path)

    for migration in migrations[current:]:
        script = f"BEGIN;\n{migration.sql}\nPRAGMA user_version = {migration.version};\nCOMMIT;"
        try:
            conn.executescript(script)
        except sqlite3.Error as error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            hint = f" Your data was backed up to {backup_path}." if backup_path else ""
            raise MigrationError(f"Migration {migration.name} failed: {error}.{hint}") from error
    return MigrationReport(current, latest, backup_path)


def open_database(db_path: Path) -> sqlite3.Connection:
    conn = connect(db_path)
    migrate(conn, db_path)
    return conn
