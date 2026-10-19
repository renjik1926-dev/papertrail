"""Text normalization with an index map (BUILD_PLAN §8.4).

`normalize(text)` returns `(normalized, index_map)` where `index_map[i]` is the position in
the original text of normalized character `i`. The same function is applied to the model's
quote and to the document text, so both sides are compared in the same form.
"""

from __future__ import annotations

import unicodedata

_CHAR_MAP = {
    "\u2018": "'",
    "\u2019": "'",
    "\u201a": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u201f": '"',
    "\u2033": '"',
    "\u2010": "-",
    "\u2011": "-",
    "\u2012": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2015": "-",
    "\u2212": "-",
    "\u00a0": " ",
    "\u202f": " ",
    "\u2007": " ",
}
_REMOVE = {"\u00ad", "\u200b", "\u200c", "\u200d", "\ufeff"}


def normalize(text: str) -> tuple[str, list[int]]:
    # 1. NFKC, one original character at a time, so every output char keeps its source index.
    chars: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        for out in unicodedata.normalize("NFKC", char):
            chars.append(out)
            origin.append(index)

    # 2. Quotes, dashes and spaces to plain forms; drop soft hyphens and zero-width marks.
    step2_chars: list[str] = []
    step2_origin: list[int] = []
    for char, index in zip(chars, origin, strict=True):
        if char in _REMOVE:
            continue
        step2_chars.append(_CHAR_MAP.get(char, char))
        step2_origin.append(index)

    # 3. De-hyphenate line breaks: "-\n" followed by a lowercase letter is removed.
    #    Done before lowercasing, so "Smith-\nJones" keeps its hyphen.
    step3_chars: list[str] = []
    step3_origin: list[int] = []
    i = 0
    n = len(step2_chars)
    while i < n:
        if (
            i + 2 < n
            and step2_chars[i] == "-"
            and step2_chars[i + 1] == "\n"
            and step2_chars[i + 2].islower()
        ):
            i += 2
            continue
        step3_chars.append(step2_chars[i])
        step3_origin.append(step2_origin[i])
        i += 1

    # 4. Lowercase (kept 1:1 with the source; a rare multi-char lowercase maps to the same index).
    # 5. Collapse whitespace runs (including newlines) to one space.
    out_chars: list[str] = []
    out_map: list[int] = []
    previous_space = False
    for char, index in zip(step3_chars, step3_origin, strict=True):
        if char.isspace():
            if previous_space:
                continue
            out_chars.append(" ")
            out_map.append(index)
            previous_space = True
            continue
        previous_space = False
        for low in char.lower():
            out_chars.append(low)
            out_map.append(index)
    return "".join(out_chars), out_map


def normalize_text(text: str) -> str:
    return normalize(text)[0]


def original_span(index_map: list[int], start: int, end: int) -> tuple[int, int]:
    """Map a normalized span [start, end) back to an original span [start, end)."""
    if start >= end:
        raise ValueError("empty span")
    return index_map[start], index_map[end - 1] + 1
