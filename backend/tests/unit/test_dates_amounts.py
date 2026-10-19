from datetime import date

import pytest

from papertrail.extract.schema import RelativeUnit
from papertrail.verify.amounts import amounts_in, parse_amount_cents
from papertrail.verify.dates import (
    add_business_days,
    add_relative,
    date_in_text,
    number_words,
    parse_date_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("December 2, 2026", date(2026, 12, 2)),
        ("Dec. 2, 2026", date(2026, 12, 2)),
        ("12/02/2026", date(2026, 12, 2)),
        ("2026-12-02", date(2026, 12, 2)),
        ("2 December 2026", date(2026, 12, 2)),
        ("by December 2nd, 2026", date(2026, 12, 2)),
        ("december 2, 2026", date(2026, 12, 2)),
    ],
)
def test_parse_full_dates(text: str, expected: date) -> None:
    assert parse_date_text(text) == expected


@pytest.mark.parametrize("text", ["December 2", "tomorrow", "in 2 days", "June 31, 2026", ""])
def test_incomplete_or_relative_dates_are_rejected(text: str) -> None:
    assert parse_date_text(text) is None


def test_relative_units() -> None:
    start = date(2026, 3, 3)
    assert add_relative(start, 60, RelativeUnit.calendar_days) == date(2026, 5, 2)
    assert add_relative(start, 2, RelativeUnit.weeks) == date(2026, 3, 17)
    assert add_relative(date(2026, 1, 31), 1, RelativeUnit.months) == date(2026, 2, 28)
    # Monday 2026-11-09 + 10 business days skips two weekends.
    assert add_business_days(date(2026, 11, 9), 10) == date(2026, 11, 23)
    # Starting on a Friday: the next business day is Monday.
    assert add_business_days(date(2026, 11, 13), 1) == date(2026, 11, 16)


def test_number_words() -> None:
    assert number_words(60) == ["sixty"]
    assert number_words(45) == ["forty-five", "forty five"]
    assert "one hundred eighty" in number_words(180)


def test_date_in_text_respects_token_boundaries() -> None:
    assert date_in_text("pay by may 30, 2026.", "May 30, 2026")
    assert not date_in_text("pay by may 30, 2026.", "May 3, 2026")
    # The same date written another way still counts.
    assert date_in_text("due 12/02/2026", "December 2, 2026")


@pytest.mark.parametrize(
    ("text", "cents"),
    [("$1,240.00", 124000), ("$237.6", 23760), ("1240", 124000), ("USD 15.00", 1500), ("$ 5", 500)],
)
def test_parse_amount_cents(text: str, cents: int) -> None:
    assert parse_amount_cents(text) == cents


def test_ambiguous_amounts_are_none() -> None:
    assert parse_amount_cents("$10.00 or $20.00") is None
    assert parse_amount_cents("about a hundred dollars") is None


def test_amounts_in_ignores_bare_integers() -> None:
    assert amounts_in("call 1-800-555-0142 in 2026 about $310.00") == [31000]
