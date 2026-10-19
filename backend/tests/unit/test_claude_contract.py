"""SDK contract tests: the real ClaudeProvider through the real SDK, with a mocked HTTP
transport (httpx2.MockTransport; anthropic 1.x is built on httpx2). No key, no network.

They assert the outgoing request (model, effort, a closed schema, no sampling parameters, no
prefill, the optional workspace header) and feed back recorded response bodies to check parsing
and stop-reason handling. An SDK upgrade that silently changes the request fails here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest

from papertrail.errors import WORKSPACE_HINT, Reason
from papertrail.extract.providers.base import ProviderError, failure_reason
from papertrail.extract.providers.claude import ClaudeProvider
from papertrail.extract.render import PROMPT_VERSION, load_prompt
from tests.conftest import RECORDINGS
from tests.unit.test_providers import walk
from tests.verify_helpers import extraction

MODEL = "claude-haiku-5-5"
DOCUMENT = '<document pages="1">\n[p1:b1] Pay $10.00 by April 2, 2027.\n</document>'


def recorded_response() -> dict[str, Any]:
    """A saved response body from eval/recorded/ (format is what the API returns)."""
    path = sorted(RECORDINGS.glob("*.json"))[0]
    response: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))["response"]
    return response


def message(stop_reason: str, text: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": MODEL,
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": text},
        ],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1200, "output_tokens": 340},
        **extra,
    }


class Recorder:
    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(self.status, json=self.body)

    @property
    def sent(self) -> dict[str, Any]:
        payload: dict[str, Any] = json.loads(self.requests[-1].content)
        return payload


def provider_for(handler: Callable[[httpx2.Request], httpx2.Response], **kw: Any) -> ClaudeProvider:
    return ClaudeProvider(
        api_key="sk-test-not-a-real-key",
        model=MODEL,
        transport=httpx2.MockTransport(handler),
        max_retries=0,
        **kw,
    )


def test_request_shape() -> None:
    recorder = Recorder(200, recorded_response())
    provider_for(recorder).extract(DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium")
    request = recorder.requests[-1]
    body = recorder.sent
    assert request.url.path == "/v1/messages"
    assert body["model"] == MODEL
    assert body["max_tokens"] == 16000
    assert body["system"] == load_prompt(PROMPT_VERSION)
    assert body["output_config"]["effort"] == "medium"
    schema = body["output_config"]["format"]["schema"]
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert all(node.get("additionalProperties") is False for node in walk(schema))
    for forbidden in ("temperature", "top_p", "top_k", "fallbacks", "thinking"):
        assert forbidden not in body
    # No assistant prefill: the conversation ends with the user's document.
    assert body["messages"] == [{"role": "user", "content": DOCUMENT}]
    assert "anthropic-workspace-id" not in request.headers


def test_workspace_header_is_sent_when_configured() -> None:
    recorder = Recorder(200, recorded_response())
    provider_for(recorder, workspace_id="wrkspc_test").extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="low"
    )
    assert recorder.requests[-1].headers["anthropic-workspace-id"] == "wrkspc_test"
    assert recorder.sent["output_config"]["effort"] == "low"


def test_end_turn_is_parsed() -> None:
    body = message("end_turn", extraction(document_date_text="March 3, 2027").model_dump_json())
    result = provider_for(Recorder(200, body)).extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
    )
    assert failure_reason(result) is None
    assert result.extraction is not None and result.extraction.document_date_text == "March 3, 2027"
    assert (result.input_tokens, result.output_tokens) == (1200, 340)
    assert result.raw["id"] == "msg_test"  # the raw body is kept for saving


def test_recorded_response_parses_through_the_sdk() -> None:
    result = provider_for(Recorder(200, recorded_response())).extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
    )
    assert result.extraction is not None


def test_refusal_with_plain_text_is_declined() -> None:
    body = message(
        "refusal",
        "I can't help with that.",
        stop_details={"type": "refusal", "category": None, "explanation": None},
    )
    result = provider_for(Recorder(200, body)).extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
    )
    assert failure_reason(result) == Reason.declined
    assert result.raw["stop_reason"] == "refusal"


def test_truncated_json_is_truncated() -> None:
    body = message("max_tokens", '{"document_type": "tax", "actions": [')
    result = provider_for(Recorder(200, body)).extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
    )
    assert failure_reason(result) == Reason.truncated


def test_invalid_json_on_end_turn_is_invalid_output() -> None:
    body = message("end_turn", '{"document_type": "tax"}')
    result = provider_for(Recorder(200, body)).extract(
        DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
    )
    assert failure_reason(result) == Reason.invalid_output


def error_body(kind: str, text: str) -> dict[str, Any]:
    return {"type": "error", "error": {"type": kind, "message": text}}


@pytest.mark.parametrize(
    ("status", "body", "reason"),
    [
        (401, error_body("authentication_error", "invalid x-api-key"), Reason.auth_error),
        (403, error_body("permission_error", "no access"), Reason.auth_error),
        (429, error_body("rate_limit_error", "slow down"), Reason.rate_limited),
        (500, error_body("api_error", "oops"), Reason.api_error),
    ],
)
def test_status_errors(status: int, body: dict[str, Any], reason: Reason) -> None:
    with pytest.raises(ProviderError) as error:
        provider_for(Recorder(status, body)).extract(
            DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
        )
    assert error.value.reason == reason
    assert "sk-test" not in error.value.message


def test_workspace_400_gets_the_plain_message() -> None:
    body = error_body(
        "invalid_request_error", "anthropic-workspace-id header is required for this key"
    )
    with pytest.raises(ProviderError) as error:
        provider_for(Recorder(400, body)).extract(
            DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium"
        )
    assert error.value.message == WORKSPACE_HINT


def test_connection_error_is_network_error() -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    with pytest.raises(ProviderError) as error:
        provider_for(broken).extract(DOCUMENT, prompt_version=PROMPT_VERSION, effort="medium")
    assert error.value.reason == Reason.network_error
