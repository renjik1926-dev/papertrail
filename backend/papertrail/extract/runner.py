"""One extraction with the retry rules from BUILD_PLAN §8.5.

- `max_tokens` (truncated): retry once at the next lower effort; at `low`, stay failed.
- output that doesn't validate (invalid_output): retry once.
- refusal (declined) and other stop reasons: no retry.
Both retries happen inside a single job attempt.
"""

from __future__ import annotations

from dataclasses import dataclass

from papertrail.config import EFFORT_ORDER
from papertrail.errors import Reason
from papertrail.extract.providers.base import (
    ExtractResult,
    Provider,
    ProviderError,
    failure_reason,
    request_hash,
)
from papertrail.extract.render import load_prompt


@dataclass(frozen=True)
class ExtractionOutcome:
    result: ExtractResult | None  # the last response received, if any
    reason: Reason | None  # None on success
    message: str
    effort: str  # effort of the last call
    request_hash: str  # hash of the last call
    input_tokens: int  # summed over every call
    output_tokens: int
    calls: int

    @property
    def ok(self) -> bool:
        return (
            self.reason is None and self.result is not None and self.result.extraction is not None
        )


def lower_effort(effort: str) -> str | None:
    index = EFFORT_ORDER.index(effort)
    return EFFORT_ORDER[index - 1] if index > 0 else None


def run_extraction(
    provider: Provider, rendered_document: str, *, prompt_version: str, effort: str
) -> ExtractionOutcome:
    prompt_text = load_prompt(prompt_version)
    current = effort
    retried_truncated = retried_invalid = False
    input_tokens = output_tokens = calls = 0
    last: ExtractResult | None = None

    while True:
        digest = request_hash(
            model=provider.model,
            effort=current,
            prompt_text=prompt_text,
            rendered_document=rendered_document,
        )
        calls += 1
        try:
            last = provider.extract(
                rendered_document, prompt_version=prompt_version, effort=current
            )
        except ProviderError as error:
            return ExtractionOutcome(
                last,
                error.reason,
                error.message,
                current,
                digest,
                input_tokens,
                output_tokens,
                calls,
            )
        input_tokens += last.input_tokens
        output_tokens += last.output_tokens
        reason = failure_reason(last)
        if reason is None:
            return ExtractionOutcome(
                last, None, "", current, digest, input_tokens, output_tokens, calls
            )
        if reason == Reason.truncated and not retried_truncated:
            lower = lower_effort(current)
            if lower is not None:
                retried_truncated = True
                current = lower
                continue
        if reason == Reason.invalid_output and not retried_invalid:
            retried_invalid = True
            continue
        message = f"stop_reason={last.stop_reason}" if reason == Reason.unexpected_stop else ""
        return ExtractionOutcome(
            last, reason, message, current, digest, input_tokens, output_tokens, calls
        )
