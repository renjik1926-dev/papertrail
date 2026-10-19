"""Property tests from BUILD_PLAN §11."""

from __future__ import annotations

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from papertrail.locate import select_words
from papertrail.parse.normalize import normalize_text
from papertrail.verify import verify_extraction
from papertrail.verify.models import CheckResult
from tests.verify_helpers import amount, deadline, extraction, make_block, make_blocks

WORDS = st.lists(
    st.sampled_from(
        [
            "the",
            "notice",
            "payment",
            "form",
            "send",
            "respond",
            "within",
            "days",
            "office",
            "account",
            "letter",
            "must",
            "your",
            "copy",
            "statement",
            "return",
            "enclosed",
            "records",
            "balance",
            "plan",
        ]
    ),
    min_size=12,
    max_size=40,
)


def _sentence(words: list[str]) -> str:
    return " ".join(words).capitalize() + "."


@settings(max_examples=60, deadline=None)
@given(WORDS, st.data())
def test_exact_substrings_always_pass_v2(words: list[str], data: st.DataObject) -> None:
    text = _sentence(words)
    blocks = make_blocks([text])
    start = data.draw(st.integers(0, len(text) - 12))
    end = data.draw(st.integers(start + 12, len(text)))
    quote = text[start:end]
    assume(normalize_text(quote).strip())
    result = verify_extraction(
        extraction(
            documents=[
                {
                    "quote": quote,
                    "block_ids": ["p1:b1"],
                    "text": "x",
                    "requirement": "required",
                    "condition": "",
                }
            ]
        ),
        blocks,
        document_sha256="0" * 64,
    )
    found = next(c for c in result.items[0].checks if c.name == "quote_found")
    assert found.result == CheckResult.passed


@settings(max_examples=60, deadline=None)
@given(WORDS, WORDS)
def test_text_from_another_document_fails_v2(words_a: list[str], words_b: list[str]) -> None:
    letter = make_blocks(["Quarterly water usage report for the north district."])
    other = "zebra quantum " + _sentence(words_b)  # shares no long run with the letter
    result = verify_extraction(
        extraction(
            documents=[
                {
                    "quote": other,
                    "block_ids": ["p1:b1"],
                    "text": "x",
                    "requirement": "required",
                    "condition": "",
                }
            ]
        ),
        letter,
        document_sha256="0" * 64,
    )
    assert result.items[0].status.value == "rejected"


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


@settings(max_examples=80, deadline=None)
@given(
    st.integers(0, 11),
    st.integers(1, 28),
    st.integers(2026, 2030),
    st.data(),
)
def test_changing_a_date_digit_fails_or_flags_v4(
    month: int, day: int, year: int, data: st.DataObject
) -> None:
    date_text = f"{MONTHS[month]} {day}, {year}"
    sentence = f"You must return the signed form to our office by {date_text} at the latest."
    digits = [i for i, ch in enumerate(date_text) if ch.isdigit()]
    position = data.draw(st.sampled_from(digits))
    replacement = data.draw(st.sampled_from([d for d in "0123456789" if d != date_text[position]]))
    changed = date_text[:position] + replacement + date_text[position + 1 :]
    quote = sentence.replace(date_text, changed)
    result = verify_extraction(
        extraction(deadlines=[deadline(quote, ["p1:b1"], date_text=changed)]),
        make_blocks([sentence]),
        document_sha256="0" * 64,
    )
    value = next((c for c in result.items[0].checks if c.name == "value_in_source"), None)
    assert value is not None and value.result in (CheckResult.flag, CheckResult.fail)
    assert result.items[0].status.value != "verified"


@settings(max_examples=80, deadline=None)
@given(st.integers(1, 99_999), st.integers(0, 99), st.data())
def test_changing_an_amount_digit_fails_or_flags_v4(
    dollars: int, cents: int, data: st.DataObject
) -> None:
    amount_text = f"${dollars:,}.{cents:02d}"
    sentence = f"The total amount due on this account is {amount_text} as of today."
    digits = [i for i, ch in enumerate(amount_text) if ch.isdigit()]
    position = data.draw(st.sampled_from(digits))
    replacement = data.draw(
        st.sampled_from([d for d in "0123456789" if d != amount_text[position]])
    )
    changed = amount_text[:position] + replacement + amount_text[position + 1 :]
    quote = sentence.replace(amount_text, changed)
    result = verify_extraction(
        extraction(amounts=[amount(quote, ["p1:b1"], changed)]),
        make_blocks([sentence]),
        document_sha256="0" * 64,
    )
    item = result.items[0]
    value = next(c for c in item.checks if c.name == "value_in_source")
    assert value.result in (CheckResult.flag, CheckResult.fail)
    assert item.status.value != "verified"


@settings(max_examples=100, deadline=None)
@given(WORDS, st.data())
def test_locate_covers_exactly_the_substring(words: list[str], data: st.DataObject) -> None:
    text = "\n".join(" ".join(words[i : i + 6]) for i in range(0, len(words), 6))
    block = make_block("p1:b1", text, seq=1)
    start = data.draw(st.integers(0, len(text) - 1))
    end = data.draw(st.integers(start + 1, len(text)))
    selected = select_words(block, start, end)
    covered = {i for w in selected for i in range(w.char_start, w.char_end)}
    for i in range(start, end):
        if not text[i].isspace():
            assert i in covered
    # Nothing selected lies entirely outside the span.
    assert all(w.char_start < end and w.char_end > start for w in selected)
