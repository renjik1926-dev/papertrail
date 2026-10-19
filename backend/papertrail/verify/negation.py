"""V9 negation: the letter says no action or payment may be needed (BUILD_PLAN §8.6)."""

from __future__ import annotations

import re

from papertrail.verify.models import Check, CheckResult

# Phrases that cancel an action or a payment when they sit in the item's own passage.
BLOCK_PHRASES = re.compile(
    r"no action is (?:needed|required)|you do not need to|you don't need to|no payment is due"
    r"|this is not a bill",
)
# "This is not a bill" is usually a banner elsewhere on the page, so it applies document-wide
# to amounts owed and payment actions.
DOCUMENT_PHRASES = re.compile(r"this is not a bill")
PAYMENT_WORDS = re.compile(r"\bpay(?:ment|ing)?\b|\bowe\b")


def check_negation(
    *,
    is_action: bool,
    is_owed_amount: bool,
    item_norm_text: str,
    source_blocks_norm: str,
    document_norm: str,
) -> Check | None:
    if not (is_action or is_owed_amount):
        return None
    hit = BLOCK_PHRASES.search(source_blocks_norm)
    if hit is None and (is_owed_amount or PAYMENT_WORDS.search(item_norm_text)):
        hit = DOCUMENT_PHRASES.search(document_norm)
    if hit is not None:
        return Check(
            name="negation",
            result=CheckResult.flag,
            detail=f'The letter says no action/payment may be needed ("{hit.group(0)}").',
        )
    return Check(
        name="negation", result=CheckResult.passed, detail="No 'not needed' wording nearby."
    )
