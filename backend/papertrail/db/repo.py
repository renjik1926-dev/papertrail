"""All SQL lives here (decision D8). Functions take a connection and return plain dicts."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from typing import Any

from papertrail.parse.models import Block, PageInfo, ParsedDocument, Word
from papertrail.verify.models import VerifiedItem

Row = dict[str, Any]

EDITABLE_FIELDS = ("text", "due_date", "amount_cents", "requirement", "condition")


def _one(cursor: sqlite3.Cursor) -> Row | None:
    row = cursor.fetchone()
    return dict(row) if row is not None else None


def _all(cursor: sqlite3.Cursor) -> list[Row]:
    return [dict(row) for row in cursor.fetchall()]


# Documents -------------------------------------------------------------------------------


def insert_document(
    conn: sqlite3.Connection, *, id: str, sha256: str, filename: str, now: str
) -> None:
    conn.execute(
        "INSERT INTO documents (id, sha256, filename, page_count, status, created_at, updated_at)"
        " VALUES (?, ?, ?, 0, 'queued', ?, ?)",
        (id, sha256, filename, now, now),
    )


def get_document(conn: sqlite3.Connection, document_id: str) -> Row | None:
    return _one(conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)))


def get_document_by_sha(conn: sqlite3.Connection, sha256: str) -> Row | None:
    return _one(conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha256,)))


def list_documents(conn: sqlite3.Connection) -> list[Row]:
    return _all(conn.execute("SELECT * FROM documents ORDER BY created_at DESC, id DESC"))


def set_document_status(
    conn: sqlite3.Connection, document_id: str, status: str, detail: str, now: str
) -> None:
    conn.execute(
        "UPDATE documents SET status = ?, status_detail = ?, updated_at = ? WHERE id = ?",
        (status, detail, now, document_id),
    )


def set_waiting_detail(conn: sqlite3.Connection, detail: str, now: str) -> int:
    """Mark every queued document with a waiting reason (e.g. daily_limit)."""
    cursor = conn.execute(
        "UPDATE documents SET status_detail = ?, updated_at = ?"
        " WHERE status = 'queued' AND status_detail != ?",
        (detail, now, detail),
    )
    return cursor.rowcount


def set_document_page_count(
    conn: sqlite3.Connection, document_id: str, page_count: int, now: str
) -> None:
    conn.execute(
        "UPDATE documents SET page_count = ?, updated_at = ? WHERE id = ?",
        (page_count, now, document_id),
    )


def set_document_ready(
    conn: sqlite3.Connection,
    document_id: str,
    *,
    run_id: str,
    document_type: str,
    document_date: str | None,
    now: str,
) -> None:
    conn.execute(
        "UPDATE documents SET status = 'ready', status_detail = '', current_run_id = ?,"
        " document_type = ?, document_date = ?, updated_at = ? WHERE id = ?",
        (run_id, document_type, document_date, now, document_id),
    )


def delete_document(conn: sqlite3.Connection, document_id: str) -> None:
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))


def all_document_hashes(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT sha256 FROM documents")}


# Pages, blocks, words --------------------------------------------------------------------


def replace_parsed(
    conn: sqlite3.Connection, document_id: str, parsed: ParsedDocument, now: str
) -> None:
    conn.execute("DELETE FROM pages WHERE document_id = ?", (document_id,))
    conn.execute("DELETE FROM blocks WHERE document_id = ?", (document_id,))  # words cascade
    conn.executemany(
        "INSERT INTO pages (document_id, page_no, width, height, is_scanned) VALUES (?, ?, ?, ?, ?)",
        [(document_id, p.page_no, p.width, p.height, int(p.is_scanned)) for p in parsed.pages],
    )
    conn.executemany(
        "INSERT INTO blocks (document_id, id, page_no, seq, text, x0, top, x1, bottom)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (document_id, b.id, b.page_no, b.seq, b.text, b.x0, b.top, b.x1, b.bottom)
            for b in parsed.blocks
        ],
    )
    conn.executemany(
        "INSERT INTO words (document_id, block_id, idx, text, char_start, char_end, x0, top, x1, bottom)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (document_id, b.id, i, w.text, w.char_start, w.char_end, w.x0, w.top, w.x1, w.bottom)
            for b in parsed.blocks
            for i, w in enumerate(b.words)
        ],
    )
    conn.execute(
        "UPDATE documents SET page_count = ?, parser_version = ?, updated_at = ? WHERE id = ?",
        (len(parsed.pages), parsed.parser_version, now, document_id),
    )


def get_pages(conn: sqlite3.Connection, document_id: str) -> list[PageInfo]:
    rows = conn.execute(
        "SELECT page_no, width, height, is_scanned FROM pages WHERE document_id = ? ORDER BY page_no",
        (document_id,),
    ).fetchall()
    return [
        PageInfo(
            page_no=r["page_no"],
            width=r["width"],
            height=r["height"],
            is_scanned=bool(r["is_scanned"]),
        )
        for r in rows
    ]


def get_blocks(conn: sqlite3.Connection, document_id: str) -> list[Block]:
    words: dict[str, list[Word]] = {}
    for r in conn.execute(
        "SELECT * FROM words WHERE document_id = ? ORDER BY block_id, idx", (document_id,)
    ).fetchall():
        words.setdefault(r["block_id"], []).append(
            Word(
                text=r["text"],
                char_start=r["char_start"],
                char_end=r["char_end"],
                x0=r["x0"],
                top=r["top"],
                x1=r["x1"],
                bottom=r["bottom"],
            )
        )
    return [
        Block(
            id=r["id"],
            page_no=r["page_no"],
            seq=r["seq"],
            text=r["text"],
            x0=r["x0"],
            top=r["top"],
            x1=r["x1"],
            bottom=r["bottom"],
            words=tuple(words.get(r["id"], [])),
        )
        for r in conn.execute(
            "SELECT * FROM blocks WHERE document_id = ? ORDER BY seq", (document_id,)
        ).fetchall()
    ]


def get_parsed(
    conn: sqlite3.Connection, document_id: str, parser_version: str
) -> ParsedDocument | None:
    """Stored parse output, if it was made by the current parser."""
    document = get_document(conn, document_id)
    if document is None or document["parser_version"] != parser_version:
        return None
    pages = get_pages(conn, document_id)
    if not pages:
        return None
    return ParsedDocument(
        parser_version=parser_version,
        pages=tuple(pages),
        blocks=tuple(get_blocks(conn, document_id)),
    )


# Runs ------------------------------------------------------------------------------------


def insert_run(
    conn: sqlite3.Connection,
    *,
    id: str,
    document_id: str,
    provider: str,
    model: str,
    prompt_version: str,
    effort: str,
    request_hash: str,
    started_at: str,
) -> None:
    conn.execute(
        "INSERT INTO runs (id, document_id, provider, model, prompt_version, effort, status,"
        " request_hash, started_at) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?)",
        (id, document_id, provider, model, prompt_version, effort, request_hash, started_at),
    )


def finish_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    status: str,
    effort: str,
    request_hash: str,
    model: str,
    stop_reason: str | None,
    error: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int,
    raw_response_path: str | None,
    finished_at: str,
) -> None:
    conn.execute(
        "UPDATE runs SET status = ?, effort = ?, request_hash = ?, model = ?, stop_reason = ?,"
        " error = ?, input_tokens = ?, output_tokens = ?, duration_ms = ?, raw_response_path = ?,"
        " finished_at = ? WHERE id = ?",
        (
            status,
            effort,
            request_hash,
            model,
            stop_reason,
            error,
            input_tokens,
            output_tokens,
            duration_ms,
            raw_response_path,
            finished_at,
            run_id,
        ),
    )


def get_run(conn: sqlite3.Connection, run_id: str) -> Row | None:
    return _one(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)))


def latest_run(conn: sqlite3.Connection, document_id: str) -> Row | None:
    return _one(
        conn.execute(
            "SELECT * FROM runs WHERE document_id = ? ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (document_id,),
        )
    )


def run_ids_for_document(conn: sqlite3.Connection, document_id: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM runs WHERE document_id = ?", (document_id,))]


def all_run_ids(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM runs")}


def count_runs_since(conn: sqlite3.Connection, *, provider: str, since: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM runs WHERE provider = ? AND started_at >= ?", (provider, since)
    ).fetchone()
    return int(row[0])


# Items -----------------------------------------------------------------------------------


def insert_items(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    run_id: str,
    items: Sequence[VerifiedItem],
    ids: dict[str, str],
    now: str,
) -> None:
    """Insert verified items. `ids` maps each item's `ref` to its new row id."""
    for item in items:
        conn.execute(
            "INSERT INTO items (id, document_id, run_id, item_key, kind, text, requirement, condition,"
            " quote, due_date, due_rule, due_calc, amount_cents, amount_role, parent_item_id, status,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                ids[item.ref],
                document_id,
                run_id,
                item.item_key,
                item.kind.value,
                item.text,
                item.requirement,
                item.condition,
                item.quote,
                item.due_date,
                item.due_rule,
                item.due_calc,
                item.amount_cents,
                item.amount_role,
                item.status.value,
                now,
            ),
        )
        conn.executemany(
            "INSERT OR IGNORE INTO item_sources (item_id, block_id, char_start, char_end) VALUES (?, ?, ?, ?)",
            [(ids[item.ref], s.block_id, s.char_start, s.char_end) for s in item.sources],
        )
        conn.executemany(
            "INSERT INTO item_rects (item_id, page_no, x0, top, x1, bottom) VALUES (?, ?, ?, ?, ?, ?)",
            [(ids[item.ref], r.page_no, r.x0, r.top, r.x1, r.bottom) for r in item.rects],
        )
        conn.executemany(
            "INSERT OR REPLACE INTO checks (item_id, name, result, detail) VALUES (?, ?, ?, ?)",
            [(ids[item.ref], c.name, c.result.value, c.detail) for c in item.checks],
        )
    for item in items:
        if item.parent_ref is not None and item.parent_ref in ids:
            conn.execute(
                "UPDATE items SET parent_item_id = ? WHERE id = ?",
                (ids[item.parent_ref], ids[item.ref]),
            )


def _attach_details(conn: sqlite3.Connection, items: list[Row]) -> list[Row]:
    if not items:
        return items
    by_id = {item["id"]: item for item in items}
    for item in items:
        item["sources"], item["rects"], item["checks"] = [], [], []
    placeholders = ",".join("?" for _ in by_id)
    keys = list(by_id)
    for r in conn.execute(
        f"SELECT * FROM item_sources WHERE item_id IN ({placeholders}) ORDER BY item_id, block_id, char_start",  # noqa: S608
        keys,
    ):
        by_id[r["item_id"]]["sources"].append(
            {"block_id": r["block_id"], "char_start": r["char_start"], "char_end": r["char_end"]}
        )
    for r in conn.execute(
        f"SELECT rowid, * FROM item_rects WHERE item_id IN ({placeholders}) ORDER BY rowid",  # noqa: S608
        keys,
    ):
        by_id[r["item_id"]]["rects"].append(
            {
                "page_no": r["page_no"],
                "x0": r["x0"],
                "top": r["top"],
                "x1": r["x1"],
                "bottom": r["bottom"],
            }
        )
    for r in conn.execute(
        f"SELECT rowid, * FROM checks WHERE item_id IN ({placeholders}) ORDER BY rowid",  # noqa: S608
        keys,
    ):
        by_id[r["item_id"]]["checks"].append(
            {"name": r["name"], "result": r["result"], "detail": r["detail"]}
        )
    return items


def list_items(conn: sqlite3.Connection, run_id: str) -> list[Row]:
    rows = _all(conn.execute("SELECT * FROM items WHERE run_id = ? ORDER BY rowid", (run_id,)))
    return _attach_details(conn, rows)


def get_item(conn: sqlite3.Connection, item_id: str) -> Row | None:
    row = _one(conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)))
    if row is None:
        return None
    return _attach_details(conn, [row])[0]


def update_item_fields(
    conn: sqlite3.Connection, item_id: str, *, review_state: str, fields: dict[str, Any]
) -> None:
    unknown = set(fields) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    assignments = ["review_state = ?"] + [f"{name} = ?" for name in fields]
    conn.execute(
        f"UPDATE items SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608 - names are whitelisted
        (review_state, *fields.values(), item_id),
    )


def insert_review(
    conn: sqlite3.Connection,
    *,
    id: str,
    item_id: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    now: str,
) -> None:
    conn.execute(
        "INSERT INTO reviews (id, item_id, action, before_json, after_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            id,
            item_id,
            action,
            json.dumps(before, sort_keys=True),
            json.dumps(after, sort_keys=True),
            now,
        ),
    )


def reviews_for_item(conn: sqlite3.Connection, item_id: str) -> list[Row]:
    return _all(
        conn.execute(
            "SELECT * FROM reviews WHERE item_id = ? ORDER BY created_at, rowid", (item_id,)
        )
    )


def reviewed_items_outside_run(
    conn: sqlite3.Connection, document_id: str, run_id: str
) -> list[Row]:
    """Reviewed items from earlier runs, newest first (for carry-over and "no longer found")."""
    return _all(
        conn.execute(
            "SELECT items.* FROM items JOIN runs ON runs.id = items.run_id"
            " WHERE items.document_id = ? AND items.run_id != ? AND items.review_state != 'none'"
            " ORDER BY runs.started_at DESC, items.rowid",
            (document_id, run_id),
        )
    )


def item_keys_in_run(conn: sqlite3.Connection, run_id: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT item_key FROM items WHERE run_id = ?", (run_id,))}


# Jobs ------------------------------------------------------------------------------------


def insert_job(conn: sqlite3.Connection, *, id: str, document_id: str, now: str) -> None:
    """Raises sqlite3.IntegrityError if the document already has a queued or running job."""
    conn.execute(
        "INSERT INTO jobs (id, document_id, status, attempts, created_at, updated_at)"
        " VALUES (?, ?, 'queued', 0, ?, ?)",
        (id, document_id, now, now),
    )


def claim_next_job(conn: sqlite3.Connection, now: str) -> Row | None:
    """Claim the oldest queued job in one statement inside BEGIN IMMEDIATE."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = _one(
            conn.execute(
                "UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = ?"
                " WHERE id = (SELECT id FROM jobs WHERE status = 'queued'"
                " ORDER BY created_at, rowid LIMIT 1) RETURNING *",
                (now,),
            )
        )
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return row


def finish_job(
    conn: sqlite3.Connection, job_id: str, *, status: str, last_error: str | None, now: str
) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, last_error = ?, updated_at = ? WHERE id = ?",
        (status, last_error, now, job_id),
    )


def requeue_job(conn: sqlite3.Connection, job_id: str, *, now: str, refund_attempt: bool) -> None:
    conn.execute(
        "UPDATE jobs SET status = 'queued', updated_at = ?,"
        " attempts = CASE WHEN ? THEN MAX(attempts - 1, 0) ELSE attempts END WHERE id = ?",
        (now, int(refund_attempt), job_id),
    )


def requeue_running(conn: sqlite3.Connection, now: str) -> int:
    """Startup recovery: a job left running by a crash goes back to the queue."""
    return conn.execute(
        "UPDATE jobs SET status = 'queued', updated_at = ? WHERE status = 'running'", (now,)
    ).rowcount


def get_job(conn: sqlite3.Connection, job_id: str) -> Row | None:
    return _one(conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)))


def active_job(conn: sqlite3.Connection, document_id: str) -> Row | None:
    return _one(
        conn.execute(
            "SELECT * FROM jobs WHERE document_id = ? AND status IN ('queued', 'running')",
            (document_id,),
        )
    )


def count_queued_jobs(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM jobs WHERE status = 'queued'").fetchone()[0])


# Settings --------------------------------------------------------------------------------


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")}


def put_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def table_counts(conn: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    allowed = {"documents", "runs", "items", "jobs", "reviews"}
    return {
        t: int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])  # noqa: S608 - whitelisted
        for t in tables
        if t in allowed
    }
