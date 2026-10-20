"""The startup sweep removes leftovers, but never a file another process may still be using."""

from __future__ import annotations

import os
import time
from pathlib import Path

from papertrail.config import Settings
from papertrail.db.connection import connect, migrate
from papertrail.store import SWEEP_MIN_AGE_S, orphan_sweep


def _make(path: Path, age_s: float) -> Path:
    path.write_bytes(b"x")
    then = time.time() - age_s
    os.utime(path, (then, then))
    return path


def test_sweep_removes_old_leftovers_and_keeps_recent_files(settings: Settings) -> None:
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    try:
        migrate(conn, settings.db_path)
        old = SWEEP_MIN_AGE_S + 60
        leftovers = [
            _make(settings.files_dir / f"{'a' * 64}.pdf", old),
            _make(settings.runs_dir / "00000000-0000-0000-0000-000000000001.json", old),
            _make(settings.tmp_dir / "abandoned.upload", old),
        ]
        in_flight = [
            _make(settings.files_dir / f"{'b' * 64}.pdf", 5),  # moved in, row not written yet
            _make(settings.runs_dir / "00000000-0000-0000-0000-000000000002.json", 5),
            _make(settings.tmp_dir / "backup-1.db", 5),  # another process's backup snapshot
        ]
        assert orphan_sweep(conn, settings) == len(leftovers)
    finally:
        conn.close()
    assert not any(p.exists() for p in leftovers)
    assert all(p.exists() for p in in_flight)
