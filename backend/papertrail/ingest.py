"""Accepting an upload (BUILD_PLAN §8.2). Ingest never opens the PDF itself.

1. `%PDF-` must appear in the first 1,024 bytes, otherwise 415 `not_a_pdf`.
2. The upload is streamed to a temporary file and refused (413 `too_large`) as soon as it
   passes the size limit.
3. SHA-256 is computed while streaming; a known hash returns the existing document.
4. The file moves to `files/<sha256>.pdf`; a `documents` row and a `jobs` row are inserted.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import transaction
from papertrail.errors import AppError, ErrorCode
from papertrail.store import new_id

HEADER_WINDOW = 1024
CHUNK = 64 * 1024
MAX_FILENAME = 200


@dataclass(frozen=True)
class IngestResult:
    document: repo.Row
    created: bool


def clean_filename(name: str | None) -> str:
    """Display only, never used as a path: keep the last path part, drop control characters."""
    base = (name or "letter.pdf").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return (base or "letter.pdf")[:MAX_FILENAME]


def too_large_error(settings: Settings) -> AppError:
    return AppError(ErrorCode.too_large, f"File is larger than {settings.max_mb} MB.")


def ingest_stream(
    conn: sqlite3.Connection,
    settings: Settings,
    stream: BinaryIO,
    filename: str | None,
    *,
    now: str,
) -> IngestResult:
    settings.ensure_dirs()
    digest = hashlib.sha256()
    size = 0
    head = b""
    fd, tmp_name = tempfile.mkstemp(dir=settings.tmp_dir, suffix=".upload")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                if len(head) < HEADER_WINDOW:
                    head += chunk[: HEADER_WINDOW - len(head)]
                    if len(head) >= HEADER_WINDOW and b"%PDF-" not in head:
                        raise AppError(ErrorCode.not_a_pdf)
                size += len(chunk)
                if size > settings.max_bytes:
                    raise too_large_error(settings)
                digest.update(chunk)
                out.write(chunk)
        if b"%PDF-" not in head:
            raise AppError(ErrorCode.not_a_pdf)

        sha = digest.hexdigest()
        existing = repo.get_document_by_sha(conn, sha)
        if existing is not None:
            return IngestResult(existing, created=False)

        final = settings.files_dir / f"{sha}.pdf"
        tmp.replace(final)
        document_id = new_id()
        try:
            with transaction(conn, immediate=True):
                repo.insert_document(
                    conn, id=document_id, sha256=sha, filename=clean_filename(filename), now=now
                )
                repo.insert_job(conn, id=new_id(), document_id=document_id, now=now)
        except sqlite3.IntegrityError:
            # The same file arrived twice at once; the other request created the row.
            existing = repo.get_document_by_sha(conn, sha)
            if existing is None:
                raise
            return IngestResult(existing, created=False)
        document = repo.get_document(conn, document_id)
        assert document is not None
        return IngestResult(document, created=True)
    finally:
        tmp.unlink(missing_ok=True)
