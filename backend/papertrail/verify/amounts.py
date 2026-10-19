"""Amounts: cents parsing, amount_valid, and V4 for amounts (BUILD_PLAN §8.6)."""

from __future__ import annotations

import re

from papertrail.extract.schema import Amount
from papertrail.verify.models import Check, CheckResult
from papertrail.verify.text import contains_value

AMOUNT_PATTERN = re.compile(
    r"(?<![\d.,])\$?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?(?![\d]|[.,]\d)"
)


def parse_amount_cents(text: str) -> int | None:
    """ "$1,240.00" -> 124000. Returns None when there is no single clear amount."""
    matches = [m for m in AMOUNT_PATTERN.finditer(text.strip()) if m.group(0).strip()]
    if len(matches) != 1:
        return None
    whole, fraction = matches[0].group(1), matches[0].group(2) or ""
    return int(whole.replace(",", "")) * 100 + int(fraction.ljust(2, "0"))


def amounts_in(text: str) -> list[int]:
    """Cents of every money-looking number: one with a "$" or with decimals."""
    out: list[int] = []
    for match in AMOUNT_PATTERN.finditer(text):
        whole, fraction = match.group(1), match.group(2)
        if "$" not in match.group(0) and fraction is None:
            continue  # a bare integer (year, phone fragment) isn't treated as money
        out.append(int(whole.replace(",", "")) * 100 + int((fraction or "").ljust(2, "0")))
    return out


def check_amount_valid(amount: Amount) -> tuple[Check, int | None]:
    cents = parse_amount_cents(amount.amount_text)
    if cents is None:
        return (
            Check(name="amount_valid", result=CheckResult.flag, detail="Couldn't read the amount."),
            None,
        )
    return Check(name="amount_valid", result=CheckResult.passed, detail="Amount read."), cents


def _amount_found(text: str, amount_text: str, cents: int | None) -> bool:
    """As written, or the same value written differently ("$1,240" vs "$1,240.00")."""
    if contains_value(text, amount_text):
        return True
    return cents is not None and cents in amounts_in(text)


def check_amount_value(
    amount: Amount, cents: int | None, *, matched_norm: str | None, document_norm: str
) -> Check:
    """V4 for amounts: `amount_text` must be in the matched passage, not just in the quote."""
    if matched_norm is not None and _amount_found(matched_norm, amount.amount_text, cents):
        return Check(
            name="value_in_source",
            result=CheckResult.passed,
            detail="The amount appears in the passage.",
        )
    if _amount_found(document_norm, amount.amount_text, cents):
        return Check(
            name="value_in_source",
            result=CheckResult.flag,
            detail="The amount was found elsewhere in the letter, not in this passage.",
        )
    return Check(
        name="value_in_source",
        result=CheckResult.fail,
        detail="The amount does not appear in the letter.",
    )
