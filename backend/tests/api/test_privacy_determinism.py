"""Privacy (NFR-1) and determinism (BUILD_PLAN §8.6) tests."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from papertrail.clock import FixedClock
from papertrail.config import Settings
from papertrail.extract.providers.fake import FakeProvider
from papertrail.logging_setup import JsonFormatter, configure_logging
from tests.conftest import FIXTURES, HEADERS, make_client, process_all, upload

MARKER = "ZQXMARKER7731"


def test_marker_never_logged_and_gone_after_delete(settings: Settings, clock: FixedClock) -> None:
    fake_settings = settings.model_copy(update={"provider": "fake"})
    configure_logging(fake_settings.logs_dir, level=logging.DEBUG)
    stream = io.StringIO()
    capture = logging.StreamHandler(stream)
    capture.setFormatter(JsonFormatter())
    logging.getLogger("papertrail").addHandler(capture)
    try:
        http, worker = make_client(fake_settings, clock, FakeProvider())
        with http:
            doc = upload(http, FIXTURES / "privacy_marker.pdf", name=f"{MARKER}.pdf")
            process_all(worker)
            items = http.get(f"/api/documents/{doc['id']}/items").json()["items"]
            assert any(MARKER in i["quote"] for i in items), "the fixture must exercise the marker"
            assert http.delete(f"/api/documents/{doc['id']}", headers=HEADERS).status_code == 204
    finally:
        logging.getLogger("papertrail").removeHandler(capture)
    logged = stream.getvalue() + "".join(
        p.read_text(encoding="utf-8") for p in fake_settings.logs_dir.glob("*.log*")
    )
    assert logged, "expected some log output"
    assert MARKER not in logged
    leftovers = [
        p.relative_to(fake_settings.data_dir)
        for p in fake_settings.data_dir.rglob("*")
        if p.is_file() and MARKER.encode() in p.read_bytes()
    ]
    assert leftovers == []


def _normalized_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    keep = (
        "kind",
        "text",
        "status",
        "due_date",
        "due_calc",
        "amount_cents",
        "item_key",
        "rects",
        "checks",
    )
    return sorted(
        ({k: item[k] for k in keep} for item in payload["items"]),
        key=lambda i: (i["item_key"], i["kind"]),
    )


def test_same_output_on_different_days(settings: Settings, tmp_path: Path) -> None:
    results = []
    for n, day in enumerate((datetime(2026, 1, 1, tzinfo=UTC), datetime(2031, 7, 4, tzinfo=UTC))):
        run_settings = settings.model_copy(update={"data_dir": tmp_path / f"day{n}"})
        http, worker = make_client(run_settings, FixedClock(day))
        with http:
            doc = upload(
                http, Path(__file__).resolve().parents[3] / "eval" / "docs" / "tax_notice_01.pdf"
            )
            process_all(worker)
            results.append(_normalized_items(http.get(f"/api/documents/{doc['id']}/items").json()))
    assert results[0] == results[1]
