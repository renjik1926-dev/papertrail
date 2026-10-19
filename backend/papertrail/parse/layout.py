"""Words -> lines -> blocks (BUILD_PLAN §8.3).

Coordinates are PDF points with the origin at the top-left of the page's visible area
(its crop box), after the page's rotation is applied — the same space pdf.js renders.
Grouping into lines and blocks happens in the page's upright space, so rotated pages still
read left to right.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from papertrail.parse.models import Block, Word

PARSER_VERSION = "layout-1"

LINE_CENTER_FACTOR = 0.5  # words join a line if centers differ by < 0.5 x median word height
# New block if the gap between one line's bottom and the next line's top is more than
# 0.6 x the median line height. The plan's starting value (1.2) merged ordinary paragraphs:
# with 11 pt text, paragraph gaps are ~13 pt and line gaps ~4 pt. Tune on the dev split.
BLOCK_GAP_FACTOR = 0.6
MIN_HORIZONTAL_OVERLAP = 0.30  # new block if overlap with the previous line is below 30%


@dataclass(frozen=True)
class RawWord:
    """A word in upright page space plus its box in display space."""

    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    display: tuple[float, float, float, float]

    @property
    def height(self) -> float:
        return self.bottom - self.top

    @property
    def center(self) -> float:
        return (self.top + self.bottom) / 2


@dataclass
class Line:
    words: list[RawWord]

    @property
    def x0(self) -> float:
        return min(w.x0 for w in self.words)

    @property
    def x1(self) -> float:
        return max(w.x1 for w in self.words)

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def center(self) -> float:
        return statistics.fmean(w.center for w in self.words)


def to_upright(
    box: tuple[float, float, float, float], rotation: int, width: float, height: float
) -> tuple[float, float, float, float]:
    """Map a display-space box back to the page's upright space.

    `width`/`height` are the display size. pdfplumber reports rotated pages in display
    space, where text on a 90-degree page runs top to bottom.
    """
    x0, top, x1, bottom = box
    if rotation == 90:
        return (top, width - x1, bottom, width - x0)
    if rotation == 180:
        return (width - x1, height - bottom, width - x0, height - top)
    if rotation == 270:
        return (height - bottom, x0, height - top, x1)
    return box


def raw_words(
    words: list[dict[str, Any]], *, rotation: int, width: float, height: float, dx: float, dy: float
) -> list[RawWord]:
    """Shift pdfplumber words into the visible box and compute their upright boxes."""
    out: list[RawWord] = []
    for word in words:
        text = str(word["text"])
        if not text.strip():
            continue
        display = (
            float(word["x0"]) - dx,
            float(word["top"]) - dy,
            float(word["x1"]) - dx,
            float(word["bottom"]) - dy,
        )
        ux0, utop, ux1, ubottom = to_upright(display, rotation, width, height)
        out.append(RawWord(text, ux0, utop, ux1, ubottom, display))
    return out


def group_lines(words: list[RawWord]) -> list[Line]:
    if not words:
        return []
    median_height = statistics.median(w.height for w in words) or 1.0
    tolerance = LINE_CENTER_FACTOR * median_height
    lines: list[Line] = []
    for word in sorted(words, key=lambda w: (w.top, w.x0)):
        if lines and abs(word.center - lines[-1].center) < tolerance:
            lines[-1].words.append(word)
        else:
            lines.append(Line([word]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    lines.sort(key=lambda line: (line.top, line.x0))
    return lines


def horizontal_overlap(a: Line, b: Line) -> float:
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    narrower = min(a.x1 - a.x0, b.x1 - b.x0)
    if narrower <= 0:
        return 0.0
    return max(0.0, overlap) / narrower


def group_blocks(lines: list[Line]) -> list[list[Line]]:
    if not lines:
        return []
    median_line_height = statistics.median(line.bottom - line.top for line in lines) or 1.0
    max_gap = BLOCK_GAP_FACTOR * median_line_height
    blocks: list[list[Line]] = []
    for line in lines:
        if blocks:
            previous = blocks[-1][-1]
            gap = line.top - previous.bottom
            if gap <= max_gap and horizontal_overlap(previous, line) >= MIN_HORIZONTAL_OVERLAP:
                blocks[-1].append(line)
                continue
        blocks.append([line])
    return blocks


def build_blocks(page_no: int, seq_start: int, lines_per_block: list[list[Line]]) -> list[Block]:
    blocks: list[Block] = []
    for n, block_lines in enumerate(lines_per_block, start=1):
        parts: list[str] = []
        words: list[Word] = []
        offset = 0
        for line_index, line in enumerate(block_lines):
            if line_index:
                parts.append("\n")
                offset += 1
            for word_index, raw in enumerate(line.words):
                if word_index:
                    parts.append(" ")
                    offset += 1
                start = offset
                parts.append(raw.text)
                offset += len(raw.text)
                dx0, dtop, dx1, dbottom = raw.display
                words.append(
                    Word(
                        text=raw.text,
                        char_start=start,
                        char_end=offset,
                        x0=dx0,
                        top=dtop,
                        x1=dx1,
                        bottom=dbottom,
                    )
                )
        blocks.append(
            Block(
                id=f"p{page_no}:b{n}",
                page_no=page_no,
                seq=seq_start + n - 1,
                text="".join(parts),
                x0=min(w.x0 for w in words),
                top=min(w.top for w in words),
                x1=max(w.x1 for w in words),
                bottom=max(w.bottom for w in words),
                words=tuple(words),
            )
        )
    return blocks


def layout_page(page_no: int, seq_start: int, words: list[RawWord]) -> list[Block]:
    return build_blocks(page_no, seq_start, group_blocks(group_lines(words)))
