"""Performance budgets (BUILD_PLAN §11), run nightly: `pytest -m slow`."""

from __future__ import annotations

import time

import pytest

from papertrail.parse import parse_pdf
from papertrail.verify import verify_extraction
from tests.conftest import FIXTURES
from tests.verify_helpers import action, extraction, make_blocks

pytestmark = pytest.mark.slow


def test_fifty_page_document_parses_quickly() -> None:
    started = time.perf_counter()
    outcome = parse_pdf(FIXTURES / "fifty_one_pages.pdf", max_pages=60)
    elapsed = time.perf_counter() - started
    assert outcome.status == "ok" and outcome.document is not None
    assert len(outcome.document.pages) == 51
    assert elapsed < 15, f"parsing took {elapsed:.1f} s"


def test_verify_and_locate_hundred_items_quickly() -> None:
    texts = [
        f"Paragraph {n}: please return form {n} to the office by the end of the month."
        for n in range(300)
    ]
    blocks = make_blocks(texts)
    items = [action(texts[n * 3], [f"p1:b{n * 3 + 1}"], f"Return form {n}") for n in range(100)]
    started = time.perf_counter()
    result = verify_extraction(extraction(actions=items), blocks, document_sha256="0" * 64)
    elapsed = time.perf_counter() - started
    assert len(result.items) == 100
    assert elapsed < 2, f"verify + locate took {elapsed:.2f} s"
