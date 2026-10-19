"""Parser: golden block dumps, coordinates, and the unsupported cases (FR-2)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from papertrail.parse import parse_pdf
from papertrail.parse.layout import to_upright
from papertrail.parse.models import ParsedDocument
from tests.conftest import FIXTURES, TESTS

GOLDEN = TESTS / "golden"
GOLDEN_FIXTURES = ["plain_letter", "two_columns", "rotated", "cropped", "privacy_marker"]
TOLERANCE = 0.05  # points; survives floating-point differences between operating systems


def dump(document: ParsedDocument) -> dict[str, Any]:
    return {
        "parser_version": document.parser_version,
        "pages": [p.model_dump() for p in document.pages],
        "blocks": [
            {
                "id": b.id,
                "page_no": b.page_no,
                "seq": b.seq,
                "text": b.text,
                "bbox": [round(v, 2) for v in (b.x0, b.top, b.x1, b.bottom)],
                "words": len(b.words),
            }
            for b in document.blocks
        ],
    }


def assert_close(actual: Any, expected: Any, path: str = "") -> None:
    if isinstance(expected, float) or isinstance(actual, float):
        assert actual == pytest.approx(expected, abs=TOLERANCE), path
    elif isinstance(expected, dict):
        assert set(actual) == set(expected), path
        for key in expected:
            assert_close(actual[key], expected[key], f"{path}.{key}")
    elif isinstance(expected, list):
        assert len(actual) == len(expected), path
        for index, (a, e) in enumerate(zip(actual, expected, strict=True)):
            assert_close(a, e, f"{path}[{index}]")
    else:
        assert actual == expected, path


@pytest.mark.parametrize("name", GOLDEN_FIXTURES)
def test_golden_block_dump(name: str) -> None:
    outcome = parse_pdf(FIXTURES / f"{name}.pdf", max_pages=50)
    assert outcome.status == "ok" and outcome.document is not None
    actual = dump(outcome.document)
    golden = GOLDEN / f"{name}.json"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        golden.write_text(json.dumps(actual, indent=1) + "\n", encoding="utf-8")
    expected = json.loads(golden.read_text(encoding="utf-8"))
    assert_close(actual, expected)


def test_blocks_ids_offsets_and_dehyphenation_input() -> None:
    outcome = parse_pdf(FIXTURES / "plain_letter.pdf", max_pages=50)
    assert outcome.document is not None
    blocks = outcome.document.blocks
    assert [b.id for b in blocks][:2] == ["p1:b1", "p1:b2"]
    assert [b.seq for b in blocks] == list(range(1, len(blocks) + 1))
    for block in blocks:
        for word in block.words:
            assert block.text[word.char_start : word.char_end] == word.text
    assert any("pay-\nment" in b.text for b in blocks)


def test_rotated_page_reads_like_the_upright_page() -> None:
    plain = parse_pdf(FIXTURES / "plain_letter.pdf", max_pages=50).document
    rotated = parse_pdf(FIXTURES / "rotated.pdf", max_pages=50).document
    assert plain is not None and rotated is not None
    assert [b.text for b in rotated.blocks] == [b.text for b in plain.blocks]
    page = rotated.pages[0]
    assert (page.width, page.height) == (792.0, 612.0)
    # Display-space boxes map back onto the upright page's boxes.
    for upright, turned in zip(plain.blocks, rotated.blocks, strict=True):
        back = to_upright(
            (turned.x0, turned.top, turned.x1, turned.bottom), 90, page.width, page.height
        )
        assert back == pytest.approx(
            (upright.x0, upright.top, upright.x1, upright.bottom), abs=TOLERANCE
        )


def test_cropped_page_is_measured_from_the_crop_box() -> None:
    plain = parse_pdf(FIXTURES / "plain_letter.pdf", max_pages=50).document
    cropped = parse_pdf(FIXTURES / "cropped.pdf", max_pages=50).document
    assert plain is not None and cropped is not None
    assert (cropped.pages[0].width, cropped.pages[0].height) == (576.0, 720.0)
    first_plain, first_cropped = plain.blocks[0], cropped.blocks[0]
    assert first_cropped.x0 == pytest.approx(first_plain.x0 - 36, abs=TOLERANCE)
    assert first_cropped.top == pytest.approx(max(0.0, first_plain.top - 72), abs=TOLERANCE)


@pytest.mark.parametrize(
    ("name", "status", "reason"),
    [
        ("encrypted", "unsupported", "encrypted"),
        ("scanned", "unsupported", "scanned"),
        ("fifty_one_pages", "unsupported", "too_many_pages"),
    ],
)
def test_unsupported_documents(name: str, status: str, reason: str) -> None:
    outcome = parse_pdf(FIXTURES / f"{name}.pdf", max_pages=50)
    assert (outcome.status, outcome.reason) == (status, reason)


def test_damaged_pdf_is_a_parse_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)
    outcome = parse_pdf(broken, max_pages=50)
    assert (outcome.status, outcome.reason) == ("failed", "parse_error")
