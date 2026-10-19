"""Scanned-page detection (BUILD_PLAN §8.3 step 7)."""

from __future__ import annotations

from typing import Any

MIN_TEXT_CHARS = 20
MIN_IMAGE_SHARE = 0.5


def is_scanned_page(
    chars: list[dict[str, Any]], images: list[dict[str, Any]], width: float, height: float
) -> bool:
    """Fewer than 20 characters of text and at least one image covering over half the page."""
    text_chars = sum(1 for c in chars if str(c.get("text", "")).strip())
    if text_chars >= MIN_TEXT_CHARS:
        return False
    page_area = width * height
    if page_area <= 0:
        return False
    for image in images:
        image_w = max(0.0, min(float(image["x1"]), width) - max(float(image["x0"]), 0.0))
        image_h = max(0.0, min(float(image["bottom"]), height) - max(float(image["top"]), 0.0))
        if image_w * image_h > MIN_IMAGE_SHARE * page_area:
            return True
    return False


def mostly_scanned(flags: list[bool]) -> bool:
    """More than half of the pages are scanned."""
    return bool(flags) and sum(flags) * 2 > len(flags)
