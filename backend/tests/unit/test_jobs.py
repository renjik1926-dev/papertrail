"""The worker: crash recovery, attempts, child-process timeout, spend guard (BUILD_PLAN §8.9)."""

from __future__ import annotations

from datetime import timedelta

from papertrail.clock import FixedClock
from papertrail.config import Settings
from papertrail.db import repo
from papertrail.db.connection import connect, migrate
from papertrail.extract.providers.fake import FakeProvider, result_for
from papertrail.ingest import ingest_stream
from papertrail.jobs import InProcessParser, ParseRunner, Worker
from tests.conftest import EVAL_DOCS, FIXTURES
from tests.helpers import slow_parse


def setup(
    settings: Settings, clock: FixedClock, *names: str, parser: object = None
) -> tuple[Worker, list[str]]:
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    migrate(conn, settings.db_path)
    ids = []
    for name in names:
        path = (
            EVAL_DOCS / f"{name}.pdf"
            if (EVAL_DOCS / f"{name}.pdf").exists()
            else FIXTURES / f"{name}.pdf"
        )
        with path.open("rb") as handle:
            ids.append(
                ingest_stream(
                    conn, settings, handle, path.name, now="2026-10-19T15:00:00Z"
                ).document["id"]
            )
    conn.close()
    worker = Worker(settings, clock, FakeProvider, parser or InProcessParser())  # type: ignore[arg-type]
    return worker, ids


def test_processes_a_document(settings: Settings, clock: FixedClock) -> None:
    worker, [doc] = setup(
        settings.model_copy(update={"provider": "fake"}), clock, "medical_bill_01"
    )
    assert worker.run_once() is True
    document = repo.get_document(worker.conn, doc)
    assert document is not None and document["status"] == "ready" and document["current_run_id"]
    assert worker.run_once() is False


def test_running_job_is_requeued_on_startup(settings: Settings, clock: FixedClock) -> None:
    worker, [_doc] = setup(settings, clock, "medical_bill_01")
    job = repo.claim_next_job(worker.conn, "2026-10-19T15:00:00Z")  # then "crash"
    assert job is not None
    assert worker.recover() == 1
    assert repo.get_job(worker.conn, job["id"])["status"] == "queued"  # type: ignore[index]


def test_crashing_job_fails_after_two_attempts(settings: Settings, clock: FixedClock) -> None:
    worker, [doc] = setup(settings, clock, "medical_bill_01")

    def boom() -> FakeProvider:
        raise RuntimeError("bug")

    worker.provider_factory = boom
    assert worker.run_once() and worker.run_once()
    job = repo.active_job(worker.conn, doc)
    assert job is None
    document = repo.get_document(worker.conn, doc)
    assert document is not None and (document["status"], document["status_detail"]) == (
        "failed",
        "internal_error",
    )


def test_parse_timeout_kills_the_child_process(settings: Settings, clock: FixedClock) -> None:
    runner = ParseRunner(timeout_s=1.0, fn=slow_parse)
    worker, [doc] = setup(settings, clock, "medical_bill_01", parser=runner)
    try:
        worker.run_once()  # attempt 1: timeout -> re-queued
        assert repo.get_document(worker.conn, doc)["status"] == "queued"  # type: ignore[index]
        worker.run_once()  # attempt 2: timeout -> failed
        document = repo.get_document(worker.conn, doc)
        assert document is not None and (document["status"], document["status_detail"]) == (
            "failed",
            "parse_timeout",
        )
    finally:
        runner.close()


def test_child_process_parses_real_pdf(settings: Settings, clock: FixedClock) -> None:
    runner = ParseRunner(timeout_s=60.0)
    try:
        outcome = runner.run(EVAL_DOCS / "tax_notice_01.pdf", 50)
    finally:
        runner.close()
    assert (
        outcome.status == "ok" and outcome.document is not None and len(outcome.document.pages) == 2
    )


def test_unsupported_documents_are_marked(settings: Settings, clock: FixedClock) -> None:
    worker, [doc] = setup(settings, clock, "encrypted")
    worker.run_once()
    document = repo.get_document(worker.conn, doc)
    assert document is not None and (document["status"], document["status_detail"]) == (
        "unsupported",
        "encrypted",
    )


class PretendClaude(FakeProvider):
    """Counts as a Claude run for the spend guard, without calling anything."""

    name = "claude"


def test_daily_cap_keeps_documents_queued_until_tomorrow(
    settings: Settings, clock: FixedClock
) -> None:
    capped = settings.model_copy(update={"provider": "claude", "max_docs_per_day": 1})
    worker, [_first, second] = setup(capped, clock, "medical_bill_01", "tax_notice_01")
    worker.provider_factory = PretendClaude
    assert worker.run_once() is True  # first document uses today's one call
    assert worker.run_once() is False  # cap reached
    document = repo.get_document(worker.conn, second)
    assert document is not None and (document["status"], document["status_detail"]) == (
        "queued",
        "daily_limit",
    )
    job = repo.active_job(worker.conn, second)
    assert job is not None and job["attempts"] == 0  # capped jobs don't use attempts
    clock.advance(timedelta(days=1))
    assert worker.run_once() is True
    assert repo.get_document(worker.conn, second)["status"] == "ready"  # type: ignore[index]


def test_reprocess_failure_keeps_previous_items(settings: Settings, clock: FixedClock) -> None:
    worker, [doc] = setup(
        settings.model_copy(update={"provider": "fake"}), clock, "medical_bill_01"
    )
    worker.run_once()
    first_run = repo.get_document(worker.conn, doc)["current_run_id"]  # type: ignore[index]
    repo.insert_job(worker.conn, id="again", document_id=doc, now="2026-10-19T16:00:00Z")
    worker.provider_factory = lambda: FakeProvider([result_for(None, stop_reason="refusal")])
    worker.run_once()
    document = repo.get_document(worker.conn, doc)
    assert document is not None
    assert document["current_run_id"] == first_run
    assert (document["status"], document["status_detail"]) == ("ready", "declined")
