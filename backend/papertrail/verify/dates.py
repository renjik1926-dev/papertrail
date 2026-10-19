"""Dates: V4 for deadlines, V5 date_valid, V6 relative_deadline (BUILD_PLAN §8.6).

The model copies dates exactly as written; all date math happens here. Nothing in this
module reads the clock: "this date has passed" is decided at display time (V7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache

import dateparser
from dateutil.relativedelta import relativedelta

from papertrail.extract.schema import Deadline, RelativeUnit
from papertrail.parse.normalize import normalize_text
from papertrail.verify.models import Check, CheckResult
from papertrail.verify.text import contains_value

_SETTINGS = {
    "DATE_ORDER": "MDY",
    "REQUIRE_PARTS": ["day", "month", "year"],
    # No relative parsing ("tomorrow"), so results never depend on the day this runs.
    "PARSERS": ["custom-formats", "absolute-time"],
    "RELATIVE_BASE": datetime(2000, 1, 1),
    "RETURN_AS_TIMEZONE_AWARE": False,
}

_MONTH = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
)
DATE_PATTERN = re.compile(
    rf"\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b"
    rf"|\b\d{{1,2}}\s+{_MONTH}\s+\d{{4}}\b"
    r"|\b\d{1,2}/\d{1,2}/\d{4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b",
    re.IGNORECASE,
)

_RECEIPT_ANCHOR = re.compile(r"\b(receive|received|receiving|receipt|get this|got this)\b")
_NOTICE_ANCHOR = re.compile(
    r"\b(date of (this|the) (notice|letter|statement|bill)|(notice|letter|statement) date"
    r"|date (above|shown|printed|on (this|the) (notice|letter|statement)))\b"
)

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(n: int) -> list[str]:
    """English spellings for 0..999, with and without hyphens ("forty-five", "forty five")."""
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        tens, ones = divmod(n, 10)
        if ones == 0:
            return [_TENS[tens]]
        return [f"{_TENS[tens]}-{_ONES[ones]}", f"{_TENS[tens]} {_ONES[ones]}"]
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = f"{_ONES[hundreds]} hundred"
        if rest == 0:
            return [head]
        return [f"{head} {tail}" for tail in number_words(rest)] + [
            f"{head} and {tail}" for tail in number_words(rest)
        ]
    return []


@lru_cache(maxsize=4096)
def parse_date_text(text: str) -> date | None:
    """A full calendar date (day, month and year), or None."""
    candidate = text.strip()
    if not candidate:
        return None
    found = DATE_PATTERN.search(candidate)
    if found:
        candidate = found.group(0)
    candidate = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", candidate)
    parsed = dateparser.parse(candidate, languages=["en"], settings=_SETTINGS)
    return parsed.date() if parsed else None


def dates_in(text: str) -> list[date]:
    out: list[date] = []
    for found in DATE_PATTERN.finditer(text):
        parsed = parse_date_text(found.group(0))
        if parsed is not None:
            out.append(parsed)
    return out


def date_in_text(norm_text: str, date_text: str) -> bool:
    """The date appears as written, or another spelling of the same date appears."""
    if contains_value(norm_text, date_text):
        return True
    wanted = parse_date_text(date_text)
    return wanted is not None and wanted in dates_in(norm_text)


def add_business_days(start: date, days: int) -> date:
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday..Friday; holidays are not counted
            remaining -= 1
    return current


def add_relative(start: date, amount: int, unit: RelativeUnit) -> date:
    if unit == RelativeUnit.calendar_days:
        return start + timedelta(days=amount)
    if unit == RelativeUnit.weeks:
        return start + timedelta(weeks=amount)
    if unit == RelativeUnit.months:
        return start + relativedelta(months=amount)
    if unit == RelativeUnit.business_days:
        return add_business_days(start, amount)
    raise ValueError(f"not a relative unit: {unit}")


_UNIT_LABEL = {
    RelativeUnit.calendar_days: "calendar days",
    RelativeUnit.business_days: "business days",
    RelativeUnit.weeks: "weeks",
    RelativeUnit.months: "months",
}


@dataclass(frozen=True)
class DateOutcome:
    checks: list[Check]
    due_date: date | None
    due_calc: str | None


def is_relative(deadline: Deadline) -> bool:
    return (
        not deadline.date_text.strip()
        and deadline.relative_amount > 0
        and deadline.relative_unit != RelativeUnit.none
    )


def resolve_document_date(document_date_text: str, document_norm: str) -> date | None:
    """The letter's own date, only if it appears in the letter and is a full date."""
    if not document_date_text.strip() or not date_in_text(document_norm, document_date_text):
        return None
    return parse_date_text(document_date_text)


def check_deadline_date(
    deadline: Deadline, *, document_date: date | None, document_norm: str
) -> DateOutcome:
    if deadline.date_text.strip():
        parsed = parse_date_text(deadline.date_text)
        if parsed is None:
            return DateOutcome(
                [
                    Check(
                        name="date_valid",
                        result=CheckResult.flag,
                        detail="Date incomplete (needs day, month and year).",
                    )
                ],
                None,
                None,
            )
        return DateOutcome(
            [
                Check(
                    name="date_valid",
                    result=CheckResult.passed,
                    detail=f"Due {parsed.isoformat()}.",
                )
            ],
            parsed,
            None,
        )

    if not is_relative(deadline):
        return DateOutcome(
            [
                Check(
                    name="date_valid",
                    result=CheckResult.flag,
                    detail="No date given for this deadline.",
                )
            ],
            None,
            None,
        )

    anchor = normalize_text(deadline.anchor_text)
    if _RECEIPT_ANCHOR.search(anchor):
        return DateOutcome(
            [
                Check(
                    name="relative_deadline",
                    result=CheckResult.flag,
                    detail="Start date depends on when you received it.",
                )
            ],
            None,
            None,
        )

    start: date | None = None
    start_label = ""
    if _NOTICE_ANCHOR.search(anchor):
        start = document_date
        start_label = "the letter's date"
    elif (anchor_date := parse_date_text(deadline.anchor_text)) is not None and date_in_text(
        document_norm, deadline.anchor_text
    ):
        start = anchor_date
        start_label = "the date in the letter"
    if start is None:
        return DateOutcome(
            [
                Check(
                    name="relative_deadline",
                    result=CheckResult.flag,
                    detail="No start date in the letter.",
                )
            ],
            None,
            None,
        )

    due = add_relative(start, deadline.relative_amount, deadline.relative_unit)
    calc = (
        f"{deadline.relative_amount} {_UNIT_LABEL[deadline.relative_unit]} from "
        f"{start.isoformat()} = {due.isoformat()}"
    )
    if deadline.relative_unit == RelativeUnit.business_days:
        check = Check(
            name="relative_deadline",
            result=CheckResult.flag,
            detail=f"Calculated from {start_label}; holidays not counted.",
        )
    else:
        check = Check(
            name="relative_deadline",
            result=CheckResult.passed,
            detail=f"Calculated from {start_label}.",
        )
    return DateOutcome([check], due, calc)


def check_deadline_value(
    deadline: Deadline, *, matched_norm: str | None, document_norm: str
) -> Check | None:
    """V4 for deadlines: the date (or the relative number) must be in the matched passage."""
    if deadline.date_text.strip():

        def found(text: str) -> bool:
            return date_in_text(text, deadline.date_text)

        label = "date"
    elif is_relative(deadline):
        spellings = [str(deadline.relative_amount), *number_words(deadline.relative_amount)]

        def found(text: str) -> bool:
            return any(contains_value(text, s) for s in spellings)

        label = "number of days"
    else:
        return None

    if matched_norm is not None and found(matched_norm):
        return Check(
            name="value_in_source",
            result=CheckResult.passed,
            detail=f"The {label} appears in the passage.",
        )
    if found(document_norm):
        return Check(
            name="value_in_source",
            result=CheckResult.flag,
            detail=f"The {label} was found elsewhere in the letter, not in this passage.",
        )
    return Check(
        name="value_in_source",
        result=CheckResult.fail,
        detail=f"The {label} does not appear in the letter.",
    )
