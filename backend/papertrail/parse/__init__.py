"""PDF -> pages, blocks and words with positions.

`parse_entry` is the child-process entry point (BUILD_PLAN §8.9): a top-level function that
takes a file path and returns plain data, so it works with the "spawn" start method.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pdfplumber
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect

from papertrail.errors import Reason
from papertrail.parse.layout import PARSER_VERSION, layout_page, raw_words
from papertrail.parse.models import Block, PageInfo, ParsedDocument, ParseOutcome
from papertrail.parse.scanned import is_scanned_page, mostly_scanned

__all__ = ["PARSER_VERSION", "parse_entry", "parse_pdf"]


def _is_password_error(error: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, PDFPasswordIncorrect | PDFEncryptionError):
            return True
        if any(isinstance(arg, PDFPasswordIncorrect | PDFEncryptionError) for arg in current.args):
            return True
        current = current.__cause__ or current.__context__
    return False


def parse_pdf(path: Path, *, max_pages: int) -> ParseOutcome:
    try:
        pdf = pdfplumber.open(path)
    except Exception as error:
        if _is_password_error(error):
            return ParseOutcome(status="unsupported", reason=Reason.encrypted)
        return ParseOutcome(status="failed", reason=Reason.parse_error)

    with pdf:
        try:
            page_count = len(pdf.pages)
        except Exception as error:
            if _is_password_error(error):
                return ParseOutcome(status="unsupported", reason=Reason.encrypted)
            return ParseOutcome(status="failed", reason=Reason.parse_error)
        if page_count > max_pages:
            return ParseOutcome(
                status="unsupported", reason=Reason.too_many_pages, page_count=page_count
            )
        try:
            document = _parse_pages(pdf)
        except Exception as error:
            if _is_password_error(error):
                return ParseOutcome(status="unsupported", reason=Reason.encrypted)
            return ParseOutcome(status="failed", reason=Reason.parse_error, page_count=page_count)

    if mostly_scanned([page.is_scanned for page in document.pages]):
        return ParseOutcome(
            status="unsupported", reason=Reason.scanned, page_count=page_count, document=document
        )
    return ParseOutcome(status="ok", page_count=page_count, document=document)


def _parse_pages(pdf: Any) -> ParsedDocument:
    pages: list[PageInfo] = []
    blocks: list[Block] = []
    for page_no, original in enumerate(pdf.pages, start=1):
        # Only what's inside the crop box is visible in a viewer; its corner is the origin.
        page = original.crop(original.cropbox, relative=False, strict=False)
        dx, dy = float(page.bbox[0]), float(page.bbox[1])
        width, height = float(page.width), float(page.height)
        rotation = int(original.rotation or 0) % 360
        words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
        page_blocks = layout_page(
            page_no,
            len(blocks) + 1,
            raw_words(words, rotation=rotation, width=width, height=height, dx=dx, dy=dy),
        )
        images = [
            {
                "x0": float(i["x0"]) - dx,
                "x1": float(i["x1"]) - dx,
                "top": float(i["top"]) - dy,
                "bottom": float(i["bottom"]) - dy,
            }
            for i in page.images
        ]
        pages.append(
            PageInfo(
                page_no=page_no,
                width=width,
                height=height,
                is_scanned=is_scanned_page(page.chars, images, width, height),
            )
        )
        blocks.extend(page_blocks)
        original.close()
    return ParsedDocument(parser_version=PARSER_VERSION, pages=tuple(pages), blocks=tuple(blocks))


def parse_entry(path: str, max_pages: int) -> dict[str, Any]:
    """Child-process entry point: simple arguments in, plain data out."""
    return parse_pdf(Path(path), max_pages=max_pages).model_dump(mode="json")
