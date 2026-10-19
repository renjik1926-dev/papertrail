"""V1 block_ids_valid, V2 quote_found, V3 quote_length (BUILD_PLAN §8.6)."""

from __future__ import annotations

from dataclasses import dataclass

from papertrail.parse.models import Block
from papertrail.parse.normalize import normalize_text
from papertrail.verify.models import Check, CheckResult
from papertrail.verify.text import Concat, Match, best_match, concat_blocks

PASS_SCORE = 92.0
APPROX_SCORE = 80.0
MIN_QUOTE_CHARS = 12


@dataclass(frozen=True)
class QuoteOutcome:
    checks: list[Check]
    match: Match | None  # the passage the quote was matched to, if any (score >= 80)


def check_block_ids(block_ids: list[str], known: dict[str, Block]) -> Check:
    if not block_ids:
        return Check(
            name="block_ids_valid", result=CheckResult.flag, detail="No source block was cited."
        )
    unknown = [block_id for block_id in block_ids if block_id not in known]
    if unknown:
        return Check(
            name="block_ids_valid",
            result=CheckResult.flag,
            detail=f"Cited a block that doesn't exist ({', '.join(unknown[:3])}).",
        )
    return Check(name="block_ids_valid", result=CheckResult.passed, detail="Cited blocks exist.")


def check_quote_length(norm_quote: str) -> Check:
    if len(norm_quote) < MIN_QUOTE_CHARS:
        return Check(
            name="quote_length", result=CheckResult.flag, detail="Quote too short to confirm."
        )
    return Check(
        name="quote_length", result=CheckResult.passed, detail="Quote is long enough to check."
    )


def _block_list(ranges_match: Match) -> str:
    ids = [r.block_id for r in ranges_match.source_ranges()]
    return ", ".join(dict.fromkeys(ids))


def check_quote(
    quote: str, block_ids: list[str], known: dict[str, Block], document: Concat
) -> QuoteOutcome:
    norm_quote = normalize_text(quote).strip()
    checks = [check_block_ids(block_ids, known)]

    if not norm_quote:
        checks.append(
            Check(name="quote_found", result=CheckResult.fail, detail="The quote is empty.")
        )
        checks.append(check_quote_length(norm_quote))
        return QuoteOutcome(checks, None)

    best: Match | None = None
    cited = [known[block_id] for block_id in dict.fromkeys(block_ids) if block_id in known]
    if cited:
        cited_concat = concat_blocks(cited)
        # Guard: partial matching aligns the shorter string inside the longer one, so a quote
        # longer than the cited text goes straight to the whole-document search.
        if len(norm_quote) <= len(cited_concat.norm):
            cited_match = best_match(norm_quote, cited_concat)
            if cited_match.score >= PASS_SCORE:
                checks.append(
                    Check(
                        name="quote_found",
                        result=CheckResult.passed,
                        detail="Quote matches the cited text.",
                    )
                )
                checks.append(check_quote_length(norm_quote))
                return QuoteOutcome(checks, cited_match)
            best = cited_match

    doc_match = best_match(norm_quote, document)
    if doc_match.score >= PASS_SCORE:
        checks.append(
            Check(
                name="quote_found",
                result=CheckResult.flag,
                detail=f"Quote found in a different part of the letter ({_block_list(doc_match)}) "
                "than the model cited.",
            )
        )
        checks.append(check_quote_length(norm_quote))
        return QuoteOutcome(checks, doc_match)
    if best is None or doc_match.score > best.score:
        best = doc_match

    if best.score >= APPROX_SCORE:
        checks.append(
            Check(
                name="quote_found",
                result=CheckResult.flag,
                detail=f"Quote only approximately matches the letter (score {best.score:.0f}).",
            )
        )
        checks.append(check_quote_length(norm_quote))
        return QuoteOutcome(checks, best)

    checks.append(
        Check(name="quote_found", result=CheckResult.fail, detail="Quote not found in the letter.")
    )
    checks.append(check_quote_length(norm_quote))
    return QuoteOutcome(checks, None)
