"""Concatenated block text with position maps, shared by V2 and the locator (§8.8)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from papertrail.parse.models import Block
from papertrail.parse.normalize import normalize, normalize_text
from papertrail.verify.models import SourceRange

BLOCK_JOINER = " "  # lets a quote run across a block boundary


@dataclass(frozen=True)
class Concat:
    text: str  # original block texts joined by BLOCK_JOINER
    pieces: tuple[tuple[str, int, int], ...]  # (block_id, start, end) in `text`
    norm: str
    norm_map: tuple[int, ...]  # normalized index -> index in `text`


def concat_blocks(blocks: Sequence[Block]) -> Concat:
    parts: list[str] = []
    pieces: list[tuple[str, int, int]] = []
    offset = 0
    for index, block in enumerate(blocks):
        if index:
            parts.append(BLOCK_JOINER)
            offset += len(BLOCK_JOINER)
        pieces.append((block.id, offset, offset + len(block.text)))
        parts.append(block.text)
        offset += len(block.text)
    text = "".join(parts)
    norm, norm_map = normalize(text)
    return Concat(text=text, pieces=tuple(pieces), norm=norm, norm_map=tuple(norm_map))


@dataclass(frozen=True)
class Match:
    score: float
    norm_start: int
    norm_end: int
    concat: Concat

    @property
    def matched_norm(self) -> str:
        return self.concat.norm[self.norm_start : self.norm_end]

    def widened_norm(self) -> str:
        """The matched text extended to whole words, so values at the edges aren't cut."""
        norm = self.concat.norm
        start, end = self.norm_start, self.norm_end
        while start > 0 and norm[start - 1] != " ":
            start -= 1
        while end < len(norm) and norm[end] != " ":
            end += 1
        return norm[start:end]

    def source_ranges(self) -> list[SourceRange]:
        if self.norm_end <= self.norm_start:
            return []
        start = self.concat.norm_map[self.norm_start]
        end = self.concat.norm_map[self.norm_end - 1] + 1
        ranges: list[SourceRange] = []
        for block_id, piece_start, piece_end in self.concat.pieces:
            lo, hi = max(start, piece_start), min(end, piece_end)
            if lo < hi:
                ranges.append(
                    SourceRange(
                        block_id=block_id, char_start=lo - piece_start, char_end=hi - piece_start
                    )
                )
        return ranges


def best_match(norm_quote: str, concat: Concat) -> Match:
    """Exact substring first (score 100), otherwise rapidfuzz's best partial alignment."""
    if not norm_quote or len(norm_quote) > len(concat.norm):
        return Match(0.0, 0, 0, concat)
    exact = concat.norm.find(norm_quote)
    if exact >= 0:
        return Match(100.0, exact, exact + len(norm_quote), concat)
    alignment = fuzz.partial_ratio_alignment(norm_quote, concat.norm)
    if alignment is None:
        return Match(0.0, 0, 0, concat)
    return Match(float(alignment.score), alignment.dest_start, alignment.dest_end, concat)


def contains_value(haystack_norm: str, value: str) -> bool:
    """Is `value` in the normalized text as a whole token (so "May 3" isn't found in "May 30")?"""
    needle = normalize_text(value).strip()
    if not needle:
        return False
    pattern = r"(?<![\w.,])" + re.escape(needle) + r"(?![\w]|[.,]\d)"
    return re.search(pattern, haystack_norm) is not None
