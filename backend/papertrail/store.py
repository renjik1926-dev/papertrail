"""Storing results, reviews and carry-over, deleting documents (BUILD_PLAN §7, §8.13)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import checkpoint, transaction
from papertrail.logging_setup import get_logger
from papertrail.verify.models import VerifiedDocument

log = get_logger("store")

REVIEW_STATE_FOR = {
    "accept": "accepted",
    "edit": "edited",
    "dismiss": "dismissed",
    "restore": "none",
}


def new_id() -> str:
    return str(uuid.uuid4())


def snapshot(item: repo.Row) -> dict[str, Any]:
    """The reviewable state of an item: its review state and editable fields."""
    return {"review_state": item["review_state"], **{f: item[f] for f in repo.EDITABLE_FIELDS}}


def save_raw_response(settings: Settings, run_id: str, raw: dict[str, Any]) -> Path:
    settings.runs_dir.mkdir(parents=True, exist_ok=True)
    path = settings.runs_dir / f"{run_id}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def store_success(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    run_id: str,
    verified: VerifiedDocument,
    now: str,
) -> None:
    """Insert the new run's items, carry reviews over, and switch the document to this run."""
    ids = {item.ref: new_id() for item in verified.items}
    with transaction(conn, immediate=True):
        repo.insert_items(
            conn, document_id=document_id, run_id=run_id, items=verified.items, ids=ids, now=now
        )
        carry_over_reviews(conn, document_id=document_id, run_id=run_id, now=now)
        repo.set_document_ready(
            conn,
            document_id,
            run_id=run_id,
            document_type=verified.document_type,
            document_date=verified.document_date,
            now=now,
        )


def carry_over_reviews(conn: sqlite3.Connection, *, document_id: str, run_id: str, now: str) -> int:
    """Copy review state and edits from earlier runs to new items with the same item_key."""
    previous: dict[str, repo.Row] = {}
    for old in repo.reviewed_items_outside_run(conn, document_id, run_id):
        previous.setdefault(old["item_key"], old)  # newest run first
    carried = 0
    for item in repo.list_items(conn, run_id):
        match = previous.get(item["item_key"])
        if match is None:
            continue
        before = snapshot(item)
        fields = {f: match[f] for f in repo.EDITABLE_FIELDS if match[f] != item[f]}
        repo.update_item_fields(conn, item["id"], review_state=match["review_state"], fields=fields)
        after = {**before, **fields, "review_state": match["review_state"]}
        repo.insert_review(
            conn,
            id=new_id(),
            item_id=item["id"],
            action="carry_over",
            before=before,
            after=after,
            now=now,
        )
        carried += 1
    return carried


def no_longer_found(conn: sqlite3.Connection, document_id: str, run_id: str) -> list[repo.Row]:
    """Items the user reviewed in an earlier run that the current run didn't find again."""
    current_keys = repo.item_keys_in_run(conn, run_id)
    seen: set[str] = set()
    out: list[repo.Row] = []
    for old in repo.reviewed_items_outside_run(conn, document_id, run_id):
        if old["item_key"] in current_keys or old["item_key"] in seen:
            continue
        seen.add(old["item_key"])
        out.append(old)
    return out


def original_snapshot(conn: sqlite3.Connection, item: repo.Row) -> dict[str, Any]:
    """What the item looked like before any review (first review's "before")."""
    reviews = repo.reviews_for_item(conn, item["id"])
    if not reviews:
        return snapshot(item)
    original: dict[str, Any] = json.loads(reviews[0]["before_json"])
    return original


def apply_review(
    conn: sqlite3.Connection, item_id: str, *, action: str, changes: dict[str, Any], now: str
) -> repo.Row | None:
    """accept / edit / dismiss / restore. Every review writes a `reviews` row."""
    with transaction(conn, immediate=True):
        item = repo.get_item(conn, item_id)
        if item is None:
            return None
        before = snapshot(item)
        fields: dict[str, Any] = {}
        if action == "edit":
            fields = {k: v for k, v in changes.items() if k in repo.EDITABLE_FIELDS}
        elif action == "restore":
            original = original_snapshot(conn, item)
            fields = {f: original[f] for f in repo.EDITABLE_FIELDS}
        state = REVIEW_STATE_FOR[action]
        repo.update_item_fields(conn, item_id, review_state=state, fields=fields)
        after = {**before, **fields, "review_state": state}
        repo.insert_review(
            conn, id=new_id(), item_id=item_id, action=action, before=before, after=after, now=now
        )
    return repo.get_item(conn, item_id)


def _unlink(path: Path) -> bool:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        log.warning(
            "could not delete file; the startup sweep will retry", extra={"path": str(path)}
        )
        return False
    return True


def delete_document(conn: sqlite3.Connection, settings: Settings, document_id: str) -> bool:
    """Database rows first (one transaction), then the original PDF and raw responses."""
    with transaction(conn, immediate=True):
        document = repo.get_document(conn, document_id)
        if document is None:
            return False
        run_ids = repo.run_ids_for_document(conn, document_id)
        repo.delete_document(conn, document_id)
    try:
        checkpoint(conn)
    except sqlite3.OperationalError:
        log.warning("WAL checkpoint after delete was busy; it will happen later")
    _unlink(settings.files_dir / f"{document['sha256']}.pdf")
    for run_id in run_ids:
        _unlink(settings.runs_dir / f"{run_id}.json")
    return True


# A file this new may belong to another PaperTrail process that's still working on it: an upload
# moved into files/ just before its row is written, or a backup snapshot in tmp/. The sweep leaves
# those for a later start.
SWEEP_MIN_AGE_S = 3600


def _settled(path: Path, now: float) -> bool:
    try:
        return now - path.stat().st_mtime >= SWEEP_MIN_AGE_S
    except OSError:
        return False


def orphan_sweep(conn: sqlite3.Connection, settings: Settings) -> int:
    """Finish deletions that failed earlier: files with no matching row are removed."""
    removed = 0
    now = time.time()
    hashes = repo.all_document_hashes(conn)
    if settings.files_dir.is_dir():
        for path in settings.files_dir.glob("*.pdf"):
            if path.stem not in hashes and _settled(path, now) and _unlink(path):
                removed += 1
    run_ids = repo.all_run_ids(conn)
    if settings.runs_dir.is_dir():
        for path in settings.runs_dir.glob("*.json"):
            if path.stem not in run_ids and _settled(path, now) and _unlink(path):
                removed += 1
    if settings.tmp_dir.is_dir():
        for path in settings.tmp_dir.iterdir():
            if path.is_file() and _settled(path, now) and _unlink(path):
                removed += 1
    return removed
