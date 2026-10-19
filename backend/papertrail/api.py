"""FastAPI app and routes (BUILD_PLAN §9). Bound to 127.0.0.1 by `papertrail serve`; no CORS."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from papertrail import __version__
from papertrail.api_models import (
    CheckOut,
    DocumentDetailOut,
    DocumentOut,
    ErrorOut,
    HealthOut,
    ItemOriginal,
    ItemOut,
    ItemsOut,
    LostItemOut,
    NoteOut,
    PageOut,
    RectOut,
    ReviewIn,
    RunSummary,
    SettingIn,
    SettingsOut,
    SourceOut,
)
from papertrail.clock import Clock, RealClock, utc_iso
from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import connect, migrate, transaction
from papertrail.errors import AppError, ErrorCode, describe
from papertrail.export.ics import build_calendar
from papertrail.extract.providers import make_provider
from papertrail.extract.providers.base import Provider
from papertrail.ingest import ingest_stream, too_large_error
from papertrail.jobs import ParseRunner, Worker
from papertrail.logging_setup import get_logger
from papertrail.pricing import estimate_cost_usd
from papertrail.security import (
    LocalHostMiddleware,
    RequestGuardMiddleware,
    SecurityHeadersMiddleware,
    allowed_origins,
)
from papertrail.store import apply_review, delete_document, new_id, no_longer_found, orphan_sweep
from papertrail.store import original_snapshot as item_original

log = get_logger("api")

KNOWN_SETTINGS = {"privacy_notice_ack"}
MULTIPART_OVERHEAD = 64 * 1024
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ErrorOut} for code in (400, 403, 404, 409, 413, 415, 422, 500)
}


def get_conn(request: Request) -> Iterator[sqlite3.Connection]:
    """One SQLite connection per request (connections aren't shared across threads)."""
    settings: Settings = request.app.state.settings
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def error_response(code: ErrorCode, message: str | None = None) -> JSONResponse:
    error = AppError(code, message)
    return JSONResponse(
        {"error": {"code": error.code.value, "message": error.message}}, status_code=error.status
    )


def create_app(
    settings: Settings,
    *,
    clock: Clock | None = None,
    provider_factory: Callable[[], Provider] | None = None,
    start_worker: bool = True,
    parse_runner: Any = None,
) -> FastAPI:
    clock = clock or RealClock()
    factory = provider_factory or (lambda: make_provider(settings))
    worker = Worker(settings, clock, factory, parse_runner or ParseRunner(settings.parse_timeout_s))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        conn = connect(settings.db_path)
        try:
            migrate(conn, settings.db_path)
            removed = orphan_sweep(conn, settings)
            if removed:
                log.info("orphan sweep removed files", extra={"count": removed})
        finally:
            conn.close()
        if start_worker:
            worker.start()
        else:
            worker.recover()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(
        title="PaperTrail",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.worker = worker
    app.state.clock = clock

    # Outermost first: Host check, then header/Origin guard; security headers on everything.
    app.add_middleware(
        RequestGuardMiddleware, origins=allowed_origins(settings.port, dev=settings.dev)
    )
    app.add_middleware(LocalHostMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    def now() -> str:
        return utc_iso(clock.now())

    # Errors ------------------------------------------------------------------------------
    @app.exception_handler(AppError)
    async def _app_error(_: Request, error: AppError) -> JSONResponse:
        return error_response(error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = error.errors()
        if any(p.get("type") == "json_invalid" for p in problems):
            return error_response(ErrorCode.bad_request)
        first = problems[0] if problems else {}
        where = ".".join(
            str(part) for part in first.get("loc", ()) if part not in ("body", "query", "path")
        )
        message = (
            f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg", ""))
        )
        return error_response(ErrorCode.validation_error, message or None)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            return error_response(ErrorCode.not_found)
        return error_response(ErrorCode.bad_request)

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, error: Exception) -> JSONResponse:
        log.error("unhandled error", exc_info=error)
        return error_response(ErrorCode.internal_error)

    # Routes ------------------------------------------------------------------------------
    @app.get("/api/health", response_model=HealthOut)
    def health() -> HealthOut:
        return HealthOut(ok=True, version=__version__, worker=worker.state)

    @app.post(
        "/api/documents",
        response_model=DocumentOut,
        status_code=201,
        responses={
            200: {"model": DocumentOut, "description": "Already uploaded"},
            **ERROR_RESPONSES,
        },
    )
    def upload(request: Request, conn: Conn, file: Annotated[UploadFile, File()]) -> Response:
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_bytes + MULTIPART_OVERHEAD:
            raise too_large_error(settings)
        result = ingest_stream(conn, settings, file.file, file.filename, now=now())
        if result.created:
            worker.wake()
        body = document_out(result.document).model_dump(mode="json")
        return JSONResponse(body, status_code=201 if result.created else 200)

    @app.get("/api/documents", response_model=list[DocumentOut])
    def list_documents(conn: Conn) -> list[DocumentOut]:
        return [document_out(row) for row in repo.list_documents(conn)]

    @app.get(
        "/api/documents/{document_id}", response_model=DocumentDetailOut, responses=ERROR_RESPONSES
    )
    def get_document(document_id: str, conn: Conn) -> DocumentDetailOut:
        return document_detail(conn, require_document(conn, document_id))

    @app.get("/api/settings", response_model=SettingsOut)
    def get_settings(conn: Conn) -> SettingsOut:
        stored = repo.get_settings(conn)
        return SettingsOut(privacy_notice_ack=stored.get("privacy_notice_ack") == "true")

    @app.put("/api/settings/{key}", response_model=SettingsOut, responses=ERROR_RESPONSES)
    def put_setting(key: str, body: SettingIn, conn: Conn) -> SettingsOut:
        if key not in KNOWN_SETTINGS:
            raise AppError(ErrorCode.not_found, "Unknown setting.")
        if body.value not in ("true", "false"):
            raise AppError(ErrorCode.validation_error, "value: must be 'true' or 'false'")
        repo.put_setting(conn, key, body.value)
        return get_settings(conn)

    @app.get(
        "/api/documents/{document_id}/file",
        response_class=FileResponse,
        responses={200: {"content": {"application/pdf": {}}}, **ERROR_RESPONSES},
    )
    def get_file(document_id: str, conn: Conn) -> FileResponse:
        row = require_document(conn, document_id)
        path = settings.files_dir / f"{row['sha256']}.pdf"
        if not path.is_file():
            raise AppError(ErrorCode.not_found)
        return FileResponse(
            path,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline", "Cache-Control": "no-store"},
        )

    @app.get(
        "/api/documents/{document_id}/items", response_model=ItemsOut, responses=ERROR_RESPONSES
    )
    def get_items(document_id: str, conn: Conn) -> ItemsOut:
        return items_payload(conn, require_document(conn, document_id))

    @app.patch("/api/items/{item_id}", response_model=ItemOut, responses=ERROR_RESPONSES)
    def review_item(item_id: str, body: ReviewIn, conn: Conn) -> ItemOut:
        changes = body.changes.model_dump(exclude_unset=True, mode="json")
        if body.action == "edit" and not changes:
            raise AppError(ErrorCode.validation_error, "changes: nothing to edit")
        if body.action != "edit" and changes:
            raise AppError(ErrorCode.validation_error, "changes: only allowed with action 'edit'")
        updated = apply_review(conn, item_id, action=body.action, changes=changes, now=now())
        if updated is None:
            raise AppError(ErrorCode.not_found, "That item no longer exists.")
        seq_of = {b.id: b.seq for b in repo.get_blocks(conn, updated["document_id"])}
        return item_out(conn, updated, seq_of)

    @app.post(
        "/api/documents/{document_id}/reprocess",
        response_model=DocumentOut,
        status_code=202,
        responses=ERROR_RESPONSES,
    )
    def reprocess(document_id: str, conn: Conn) -> DocumentOut:
        require_document(conn, document_id)
        stamp = now()
        try:
            with transaction(conn, immediate=True):
                repo.insert_job(conn, id=new_id(), document_id=document_id, now=stamp)
                repo.set_document_status(conn, document_id, "queued", "", stamp)
        except sqlite3.IntegrityError:
            raise AppError(ErrorCode.job_in_progress) from None
        worker.wake()
        return document_out(require_document(conn, document_id))

    @app.get(
        "/api/documents/{document_id}/calendar.ics",
        response_class=Response,
        responses={200: {"content": {"text/calendar": {}}}, **ERROR_RESPONSES},
    )
    def calendar(document_id: str, conn: Conn) -> Response:
        row = require_document(conn, document_id)
        items = repo.list_items(conn, row["current_run_id"]) if row["current_run_id"] else []
        body, skipped = build_calendar(items, document_name=row["filename"], stamp=clock.now())
        return Response(
            body,
            media_type="text/calendar",
            headers={
                "Content-Disposition": 'attachment; filename="papertrail-deadlines.ics"',
                "X-PaperTrail-Skipped": str(skipped),
                "Cache-Control": "no-store",
            },
        )

    @app.delete("/api/documents/{document_id}", status_code=204, responses=ERROR_RESPONSES)
    def remove(document_id: str, conn: Conn) -> Response:
        if not delete_document(conn, settings, document_id):
            raise AppError(ErrorCode.not_found)
        return Response(status_code=204)

    @app.api_route(
        "/api/{rest:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def api_not_found(rest: str) -> Response:
        return error_response(ErrorCode.not_found, "Unknown API endpoint.")

    mount_frontend(app, settings.static_dir)
    return app


def require_document(conn: sqlite3.Connection, document_id: str) -> repo.Row:
    row = repo.get_document(conn, document_id)
    if row is None:
        raise AppError(ErrorCode.not_found)
    return row


def document_detail(conn: sqlite3.Connection, row: repo.Row) -> DocumentDetailOut:
    document_id = row["id"]
    current = repo.get_run(conn, row["current_run_id"]) if row["current_run_id"] else None
    last = repo.latest_run(conn, document_id)
    return DocumentDetailOut(
        **document_out(row).model_dump(),
        pages=[
            PageOut(page_no=p.page_no, width=p.width, height=p.height)
            for p in repo.get_pages(conn, document_id)
        ],
        current_run=run_summary(current) if current else None,
        last_run=run_summary(last) if last else None,
        job_active=repo.active_job(conn, document_id) is not None,
    )


def items_payload(conn: sqlite3.Connection, row: repo.Row) -> ItemsOut:
    """Items of the current run, plus notes and "no longer found" (BUILD_PLAN §8.13)."""
    document_id = row["id"]
    run_id = row["current_run_id"]
    if not run_id:
        return ItemsOut(run_id=None, items=[], notes=[], no_longer_found=[])
    rows = repo.list_items(conn, run_id)
    seq_of = {b.id: b.seq for b in repo.get_blocks(conn, document_id)}
    regular = [r for r in rows if r["kind"] != "uncertainty"]
    used_blocks = {s["block_id"] for r in regular for s in r["sources"]}
    notes = [
        NoteOut(id=r["id"], text=r["text"], quote=r["quote"])
        for r in rows
        if r["kind"] == "uncertainty" and not ({s["block_id"] for s in r["sources"]} & used_blocks)
    ]
    lost = [
        LostItemOut(id=r["id"], kind=r["kind"], text=r["text"], review_state=r["review_state"])
        for r in no_longer_found(conn, document_id, run_id)
    ]
    return ItemsOut(
        run_id=run_id,
        items=[item_out(conn, r, seq_of) for r in regular],
        notes=notes,
        no_longer_found=lost,
    )


def document_out(row: repo.Row) -> DocumentOut:
    detail = row["status_detail"]
    info = describe(detail) if detail else None
    return DocumentOut(
        id=row["id"],
        filename=row["filename"],
        page_count=row["page_count"],
        status=row["status"],
        status_detail=detail,
        status_message=info.message if info else None,
        next_step=info.next_step if info else None,
        document_type=row["document_type"],
        document_date=row["document_date"],
        current_run_id=row["current_run_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def run_summary(row: repo.Row) -> RunSummary:
    return RunSummary(
        id=row["id"],
        provider=row["provider"],
        model=row["model"],
        prompt_version=row["prompt_version"],
        effort=row["effort"],
        status=row["status"],
        stop_reason=row["stop_reason"],
        error=row["error"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        estimated_cost_usd=estimate_cost_usd(
            row["model"], row["input_tokens"], row["output_tokens"]
        )
        if row["provider"] == "claude"
        else None,
        duration_ms=row["duration_ms"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def item_out(conn: sqlite3.Connection, row: repo.Row, seq_of: dict[str, int]) -> ItemOut:
    sources = row["sources"]
    if sources:
        first = min(sources, key=lambda s: (seq_of.get(s["block_id"], 10**6), s["char_start"]))
        position = seq_of.get(first["block_id"], 10**6) * 100_000 + int(first["char_start"])
    else:
        position = 10**12
    original: ItemOriginal | None = None
    if row["review_state"] == "edited" or (
        row["review_state"] == "dismissed" and repo.reviews_for_item(conn, row["id"])
    ):
        snap = item_original(conn, row)
        if any(snap[f] != row[f] for f in repo.EDITABLE_FIELDS):
            original = ItemOriginal(**{f: snap[f] for f in repo.EDITABLE_FIELDS})
    checks = [CheckOut(**c) for c in row["checks"]]
    return ItemOut(
        id=row["id"],
        kind=row["kind"],
        text=row["text"],
        requirement=row["requirement"],
        condition=row["condition"],
        quote=row["quote"],
        due_date=row["due_date"],
        due_rule=row["due_rule"],
        due_calc=row["due_calc"],
        amount_cents=row["amount_cents"],
        amount_role=row["amount_role"],
        parent_item_id=row["parent_item_id"],
        status=row["status"],
        review_state=row["review_state"],
        item_key=row["item_key"],
        position=position,
        page_no=row["rects"][0]["page_no"] if row["rects"] else None,
        sources=[SourceOut(**s) for s in sources],
        rects=[RectOut(**r) for r in row["rects"]],
        checks=checks,
        reasons=reasons_from(checks),
        original=original,
    )


def reasons_from(checks: list[CheckOut]) -> list[str]:
    """Details of every check that didn't pass, fails first."""
    order = {"fail": 0, "flag": 1}
    return [
        c.detail
        for c in sorted((c for c in checks if c.result != "pass"), key=lambda c: order[c.result])
    ]


def mount_frontend(app: FastAPI, static_dir: Path) -> None:
    """Serve the built frontend on the same origin; app routes fall back to index.html."""
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> Response:
        if not index.is_file():
            return JSONResponse(
                {
                    "error": {
                        "code": "not_found",
                        "message": "The frontend isn't built. Run the Vite dev server, or install a release.",
                    }
                },
                status_code=404,
            )
        root = static_dir.resolve()
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-store"})
