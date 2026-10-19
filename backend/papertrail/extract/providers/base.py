"""Provider interface (BUILD_PLAN §8.5, decision D9): Claude, Replay and Fake."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from typing import Any, Protocol

import pydantic

from papertrail.errors import Reason
from papertrail.extract.schema import Extraction, Strict


class ExtractResult(Strict):
    extraction: Extraction | None  # None if the output couldn't be used
    stop_reason: str
    model: str
    input_tokens: int
    output_tokens: int
    raw: dict[str, Any]  # full response body, saved to disk


class Provider(Protocol):
    name: str
    model: str

    def extract(
        self, rendered_document: str, *, prompt_version: str, effort: str
    ) -> ExtractResult: ...


class ProviderError(Exception):
    """A failed call. `reason` is one of the failure reasons in errors.py.

    Messages are written by us, never copied from the SDK, so they can't carry the API key
    or document text into logs.
    """

    def __init__(self, reason: Reason, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status_code = status_code


@cache
def schema_json() -> str:
    """Our emitted JSON schema for Extraction, serialized deterministically."""
    return json.dumps(Extraction.model_json_schema(), sort_keys=True, separators=(",", ":"))


def request_hash(*, model: str, effort: str, prompt_text: str, rendered_document: str) -> str:
    """SHA-256 of everything that shapes the answer (BUILD_PLAN §8.5, Replay provider).

    Hashing the prompt's contents (not just its version label), the schema and the exact
    document text means a change to any of them can never silently replay a stale answer.
    """
    payload = json.dumps(
        {
            "model": model,
            "effort": effort,
            "prompt": prompt_text,
            "schema": schema_json(),
            "document": rendered_document,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def text_of(raw: dict[str, Any]) -> str:
    """Concatenate text blocks, read by type (thinking blocks may come first)."""
    parts = [
        str(block.get("text", ""))
        for block in raw.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    return "".join(parts)


def usage_of(raw: dict[str, Any]) -> tuple[int, int]:
    usage = raw.get("usage") or {}
    return int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)


def result_from_raw(
    raw: dict[str, Any], *, model: str, parsed: Extraction | None = None
) -> ExtractResult:
    """Interpret a raw Messages API response body.

    Only an `end_turn` response is used; for anything else `extraction` is None and the
    caller maps the stop reason to a failure (see `failure_reason`).
    """
    stop_reason = str(raw.get("stop_reason") or "")
    extraction: Extraction | None = None
    if stop_reason == "end_turn":
        if parsed is not None:
            extraction = parsed
        else:
            try:
                extraction = Extraction.model_validate_json(text_of(raw))
            except pydantic.ValidationError:
                extraction = None
    input_tokens, output_tokens = usage_of(raw)
    return ExtractResult(
        extraction=extraction,
        stop_reason=stop_reason,
        model=str(raw.get("model") or model),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        raw=raw,
    )


def failure_reason(result: ExtractResult) -> Reason | None:
    """BUILD_PLAN §8.5: check the stop reason before using the result."""
    if result.stop_reason == "end_turn":
        return None if result.extraction is not None else Reason.invalid_output
    if result.stop_reason == "max_tokens":
        return Reason.truncated
    if result.stop_reason == "refusal":
        return Reason.declined
    return Reason.unexpected_stop
