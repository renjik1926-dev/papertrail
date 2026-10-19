"""BUILD_PLAN §8.4: the index map is non-decreasing, in range, and maps spans back exactly."""

import itertools

from hypothesis import given, settings
from hypothesis import strategies as st

from papertrail.parse.normalize import normalize, normalize_text, original_span

# Text with the characters normalization cares about: quotes, dashes, odd spaces,
# soft hyphens, ligatures, line breaks and mixed case.
ALPHABET = st.sampled_from(
    [*list("abcdefXYZ 019-.,$\n\t"), "’", "“", "—", "\xa0", "\xad", "ﬁ", "Ⅰ"]
)
TEXT = st.text(alphabet=ALPHABET, max_size=60)


@given(TEXT)
def test_map_is_non_decreasing_and_in_range(text: str) -> None:
    norm, index_map = normalize(text)
    assert len(norm) == len(index_map)
    assert all(0 <= i < len(text) for i in index_map)
    assert all(a <= b for a, b in itertools.pairwise(index_map))


def _boundary(index_map: list[int], i: int) -> bool:
    """A position that doesn't split one original character's expansion (e.g. a ligature)."""
    return i in (0, len(index_map)) or index_map[i - 1] != index_map[i]


@settings(max_examples=300)
@given(TEXT, st.data())
def test_span_maps_back_to_same_normalized_text(text: str, data: st.DataObject) -> None:
    norm, index_map = normalize(text)
    if not norm:
        return
    start = data.draw(st.integers(0, len(norm) - 1))
    end = data.draw(st.integers(start + 1, len(norm)))
    if not (_boundary(index_map, start) and _boundary(index_map, end)):
        return
    lo, hi = original_span(index_map, start, end)
    assert normalize_text(text[lo:hi]) == norm[start:end]


@given(TEXT)
def test_idempotent(text: str) -> None:
    once = normalize_text(text)
    assert normalize_text(once) == once
