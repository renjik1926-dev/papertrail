"""V10 injection: text addressed to an AI inside the letter (BUILD_PLAN §8.6)."""

from __future__ import annotations

import re

from papertrail.verify.models import Check, CheckResult

PATTERNS = re.compile(
    r"ignore (?:all |any |the )?(?:previous|prior|above|earlier)"
    r" (?:instructions|directions|prompts?)"
    r"|disregard (?:all |any |the )?(?:previous|prior|above|earlier)"
    r"|system prompt|ai assistant|language model|as an ai\b|\bllm\b"
    r"|new instructions|you are (?:chatgpt|claude|an ai)",
)


def check_injection(quote_norm: str, source_blocks_norm: str) -> Check:
    hit = PATTERNS.search(quote_norm) or PATTERNS.search(source_blocks_norm)
    if hit is not None:
        return Check(
            name="injection",
            result=CheckResult.flag,
            detail="Unusual instruction in the document (text addressed to an AI).",
        )
    return Check(name="injection", result=CheckResult.passed, detail="No text addressed to an AI.")
