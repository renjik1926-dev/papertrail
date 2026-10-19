"""Quote -> highlight rectangles (BUILD_PLAN §8.8)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from papertrail.parse.models import Block, Word
from papertrail.verify.models import Rect, SourceRange

PADDING = 1.0  # points


def select_words(block: Block, char_start: int, char_end: int) -> list[Word]:
    """Words whose [char_start, char_end) overlaps the span."""
    return [w for w in block.words if w.char_start < char_end and w.char_end > char_start]


def line_of(block: Block, word: Word) -> int:
    return block.text.count("\n", 0, word.char_start)


def locate(sources: Sequence[SourceRange], blocks: Mapping[str, Block]) -> list[Rect]:
    """One rectangle per (page, block, line) touched by the sources, with 1 pt padding."""
    grouped: dict[tuple[int, str, int], list[Word]] = {}
    order: list[tuple[int, str, int]] = []
    for source in sources:
        block = blocks.get(source.block_id)
        if block is None:
            continue
        for word in select_words(block, source.char_start, source.char_end):
            key = (block.page_no, block.id, line_of(block, word))
            if key not in grouped:
                grouped[key] = []
                order.append(key)
            if word not in grouped[key]:
                grouped[key].append(word)
    rects: list[Rect] = []
    for key in order:
        words = grouped[key]
        rects.append(
            Rect(
                page_no=key[0],
                x0=round(max(0.0, min(w.x0 for w in words) - PADDING), 2),
                top=round(max(0.0, min(w.top for w in words) - PADDING), 2),
                x1=round(max(w.x1 for w in words) + PADDING, 2),
                bottom=round(max(w.bottom for w in words) + PADDING, 2),
            )
        )
    return rects
