"""The jobs table worker (BUILD_PLAN §8.9).

One worker thread claims queued jobs and runs the pipeline. Parsing runs in a child process
with a timeout, so a malformed PDF can't hang the app: a thread can't be stopped, but a
stuck child process can.
"""

from __future__ import annotations

import concurrent.futures
import multiprocessing
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

from papertrail.clock import Clock, local_day_start_utc, local_midnight_after, utc_iso
from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import connect, transaction
from papertrail.errors import Reason
from papertrail.extract.providers.base import Provider
from papertrail.extract.render import PROMPT_VERSION
from papertrail.logging_setup import get_logger
from papertrail.parse import PARSER_VERSION, parse_entry, parse_pdf
from papertrail.parse.models import ParseOutcome
from papertrail.pipeline import extract_and_verify
from papertrail.store import new_id, save_raw_response, store_success

log = get_logger("jobs")

MAX_ATTEMPTS = 2
IDLE_WAIT_S = 2.0

ParseFn = Callable[[str, int], dict[str, Any]]


class ParseTimeoutError(Exception):
    pass


class ParseRunner:
    """Runs `parse_entry` in a one-process pool with a timeout.

    Uses the "spawn" start method everywhere (the default on Windows and macOS), so the entry
    point must be a top-level function taking a path and returning plain data.
    """

    def __init__(self, timeout_s: float, fn: ParseFn = parse_entry) -> None:
        self.timeout_s = timeout_s
        self.fn = fn
        self._pool: concurrent.futures.ProcessPoolExecutor | None = None

    def _get_pool(self) -> concurrent.futures.ProcessPoolExecutor:
        if self._pool is None:
            self._pool = concurrent.futures.ProcessPoolExecutor(
                max_workers=1, mp_context=multiprocessing.get_context("spawn")
            )
        return self._pool

    def run(self, path: Path, max_pages: int) -> ParseOutcome:
        pool = self._get_pool()
        future = pool.submit(self.fn, str(path), max_pages)
        try:
            data = future.result(timeout=self.timeout_s)
        except concurrent.futures.TimeoutError:
            self._kill_pool()
            raise ParseTimeoutError from None
        except BrokenProcessPool:
            self._kill_pool()
            return ParseOutcome(status="failed", reason=Reason.parse_error)
        return ParseOutcome.model_validate(data)

    def _kill_pool(self) -> None:
        """A stuck worker can't be reused: terminate it and start a new pool next time."""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        terminate = getattr(pool, "terminate_workers", None)  # Python 3.14+
        if callable(terminate):
            terminate()
        else:
            for process in list(getattr(pool, "_processes", {}).values()):
                process.terminate()
        pool.shutdown(wait=False, cancel_futures=True)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=True)
            self._pool = None


class InProcessParser:
    """Same interface without a child process (CLI and fast tests)."""

    def run(self, path: Path, max_pages: int) -> ParseOutcome:
        return parse_pdf(path, max_pages=max_pages)

    def close(self) -> None:
        return None


class Worker:
    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        provider_factory: Callable[[], Provider],
        parser: ParseRunner | InProcessParser,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.provider_factory = provider_factory
        self.parser = parser
        self.state = "stopped"
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: sqlite3.Connection | None = None

    # Lifecycle ---------------------------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = connect(self.settings.db_path)  # the worker's own connection
        return self._conn

    def recover(self) -> int:
        """Startup: any job left `running` by a crash goes back to the queue."""
        return repo.requeue_running(self.conn, self._now())

    def start(self) -> None:
        self.recover()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="papertrail-worker", daemon=True)
        self._thread.start()
        self.state = "running"

    def stop(self, timeout: float = 10.0) -> None:
        """Stop claiming new jobs. A job cut off mid-way is re-queued by `recover`."""
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
        self.parser.close()
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        self.state = "stopped"

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.run_once()
            except Exception:
                log.exception("worker loop error")
                worked = False
            if not worked:
                self._wake.wait(IDLE_WAIT_S)
                self._wake.clear()

    def _now(self) -> str:
        return utc_iso(self.clock.now())

    # Spend guard -------------------------------------------------------------------------
    def daily_limit_reached(self) -> bool:
        if self.settings.provider != "claude":
            return False
        started_today = repo.count_runs_since(
            self.conn, provider="claude", since=local_day_start_utc(self.clock)
        )
        return started_today >= self.settings.max_docs_per_day

    def _sleep_until_midnight(self) -> None:
        self.state = "waiting_daily_limit"
        seconds = (local_midnight_after(self.clock) - self.clock.now()).total_seconds()
        self._stop.wait(max(1.0, seconds))
        if not self._stop.is_set():
            self.state = "running"

    # One job -----------------------------------------------------------------------------
    def run_once(self) -> bool:
        """Claim and process one job. Returns False when there was nothing to do."""
        if repo.count_queued_jobs(self.conn) == 0:
            return False
        if self.daily_limit_reached():
            # Capped jobs stay queued and don't use up attempts; no polling until midnight.
            repo.set_waiting_detail(self.conn, Reason.daily_limit.value, self._now())
            if self._thread is not None and threading.current_thread() is self._thread:
                self._sleep_until_midnight()
            return False
        job = repo.claim_next_job(self.conn, self._now())
        if job is None:
            return False
        try:
            self._process(job)
        except Exception as error:
            log.exception(
                "job crashed", extra={"job_id": job["id"], "document_id": job["document_id"]}
            )
            self._job_crashed(job, type(error).__name__)
        return True

    def _job_crashed(self, job: repo.Row, error_name: str) -> None:
        now = self._now()
        if job["attempts"] < MAX_ATTEMPTS:
            repo.requeue_job(self.conn, job["id"], now=now, refund_attempt=False)
            return
        repo.finish_job(self.conn, job["id"], status="failed", last_error=error_name, now=now)
        repo.set_document_status(self.conn, job["document_id"], "failed", "internal_error", now)

    def _process(self, job: repo.Row) -> None:
        conn = self.conn
        document = repo.get_document(conn, job["document_id"])
        if document is None:  # deleted while queued
            repo.finish_job(conn, job["id"], status="done", last_error=None, now=self._now())
            return
        document_id = document["id"]
        context = {"job_id": job["id"], "document_id": document_id}

        # 1. Parse (reuse stored blocks when the parser hasn't changed, e.g. on re-process).
        parsed = repo.get_parsed(conn, document_id, PARSER_VERSION)
        if parsed is None:
            repo.set_document_status(conn, document_id, "parsing", "", self._now())
            started = time.monotonic()
            path = self.settings.files_dir / f"{document['sha256']}.pdf"
            try:
                outcome = self.parser.run(path, self.settings.max_pages)
            except ParseTimeoutError:
                log.warning("parse timed out", extra={**context, "step": "parse"})
                if job["attempts"] < MAX_ATTEMPTS:
                    repo.requeue_job(conn, job["id"], now=self._now(), refund_attempt=False)
                    repo.set_document_status(conn, document_id, "queued", "", self._now())
                else:
                    self._fail(job, document, Reason.parse_timeout)
                return
            log.info(
                "parsed",
                extra={
                    **context,
                    "step": "parse",
                    "status": outcome.status,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            if outcome.status == "unsupported":
                with transaction(conn):
                    repo.set_document_page_count(conn, document_id, outcome.page_count, self._now())
                    repo.set_document_status(
                        conn, document_id, "unsupported", outcome.reason, self._now()
                    )
                    repo.finish_job(
                        conn, job["id"], status="done", last_error=None, now=self._now()
                    )
                return
            if outcome.status != "ok" or outcome.document is None:
                self._fail(job, document, Reason(outcome.reason or Reason.parse_error))
                return
            parsed = outcome.document
            with transaction(conn):
                repo.replace_parsed(conn, document_id, parsed, self._now())

        # 2. Extract (the one AI call) and 3. verify.
        repo.set_document_status(conn, document_id, "extracting", "", self._now())
        provider = self.provider_factory()
        run_id = new_id()
        repo.insert_run(
            conn,
            id=run_id,
            document_id=document_id,
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            effort=self.settings.effort,
            request_hash="",
            started_at=self._now(),
        )
        started = time.monotonic()
        result = extract_and_verify(
            parsed,
            document_sha256=document["sha256"],
            provider=provider,
            effort=self.settings.effort,
        )
        outcome_ = result.extraction
        duration_ms = int((time.monotonic() - started) * 1000)
        raw_path = (
            save_raw_response(self.settings, run_id, outcome_.result.raw)
            if outcome_.result
            else None
        )
        failed = result.verified is None
        repo.finish_run(
            conn,
            run_id,
            status="failed" if failed else "succeeded",
            effort=outcome_.effort,
            request_hash=outcome_.request_hash,
            model=outcome_.result.model if outcome_.result else provider.model,
            stop_reason=outcome_.result.stop_reason if outcome_.result else None,
            error=(outcome_.reason.value if outcome_.reason else None),
            input_tokens=outcome_.input_tokens,
            output_tokens=outcome_.output_tokens,
            duration_ms=duration_ms,
            raw_response_path=str(raw_path) if raw_path else None,
            finished_at=self._now(),
        )
        log.info(
            "extracted",
            extra={
                **context,
                "run_id": run_id,
                "step": "extract",
                "duration_ms": duration_ms,
                "input_tokens": outcome_.input_tokens,
                "output_tokens": outcome_.output_tokens,
                "status": "failed" if failed else "succeeded",
                "reason": outcome_.reason.value if outcome_.reason else None,
            },
        )
        if result.verified is None:
            self._fail(
                job,
                repo.get_document(conn, document_id) or document,
                outcome_.reason or Reason.api_error,
            )
            return

        repo.set_document_status(conn, document_id, "verifying", "", self._now())
        store_success(
            conn, document_id=document_id, run_id=run_id, verified=result.verified, now=self._now()
        )
        repo.finish_job(conn, job["id"], status="done", last_error=None, now=self._now())

    def _fail(self, job: repo.Row, document: repo.Row, reason: Reason) -> None:
        """A failed step. If an earlier run exists, keep showing it with a notice."""
        now = self._now()
        with transaction(self.conn):
            if document.get("current_run_id"):
                repo.set_document_status(self.conn, document["id"], "ready", reason.value, now)
            else:
                repo.set_document_status(self.conn, document["id"], "failed", reason.value, now)
            repo.finish_job(self.conn, job["id"], status="failed", last_error=reason.value, now=now)
