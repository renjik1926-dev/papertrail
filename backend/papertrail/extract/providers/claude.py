"""The one real AI call: Claude through `client.messages.parse` (BUILD_PLAN §8.5).

Rules for Claude Haiku 5.5 that shape this request:
- no `temperature`, `top_p` or `top_k` (non-default values return 400) and no prefill;
- `effort` is set explicitly in `output_config` (the SDK merges it with the schema);
- thinking is on by default, so content blocks are read by type, and `max_tokens` is generous;
- `refusal` has no server-side fallback on this model, so `fallbacks` is not sent.
"""

from __future__ import annotations

import threading
from typing import Any, Literal, cast

import anthropic
import httpx2
import pydantic
from anthropic.types import OutputConfigParam

from papertrail.errors import WORKSPACE_HINT, Reason
from papertrail.extract.providers.base import ExtractResult, ProviderError, result_from_raw
from papertrail.extract.render import load_prompt
from papertrail.extract.schema import Extraction

MAX_TOKENS = 16000
WORKSPACE_HEADER = "anthropic-workspace-id"


EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]
_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _effort(value: str) -> EffortLevel:
    if value not in _EFFORTS:
        raise ValueError(f"unknown effort: {value}")
    return cast(EffortLevel, value)


class _ResponseCapture:
    """Keeps the last successful /v1/messages response body, per thread.

    `messages.parse` validates the text block while building its result, so a refusal or a
    truncated answer raises before we could read `stop_reason`. Reading the body in an HTTP
    response hook means the raw response is always available to classify and to save.
    """

    def __init__(self) -> None:
        self._local = threading.local()

    def clear(self) -> None:
        self._local.body = None

    @property
    def body(self) -> dict[str, Any] | None:
        body: dict[str, Any] | None = getattr(self._local, "body", None)
        return body

    def hook(self, response: httpx2.Response) -> None:
        if response.status_code != 200 or not response.request.url.path.endswith("/v1/messages"):
            return
        response.read()
        try:
            data = response.json()
        except ValueError:
            return
        if isinstance(data, dict):
            self._local.body = data


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        workspace_id: str | None = None,
        timeout_s: float = 180.0,
        max_retries: int = 2,
        transport: httpx2.BaseTransport | None = None,
        base_url: str | None = None,
    ) -> None:
        self.model = model
        self._capture = _ResponseCapture()
        http_kwargs: dict[str, Any] = {"event_hooks": {"response": [self._capture.hook]}}
        if transport is not None:
            http_kwargs["transport"] = transport
        default_headers = {WORKSPACE_HEADER: workspace_id} if workspace_id else None
        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            default_headers=default_headers,
            http_client=anthropic.DefaultHttpxClient(**http_kwargs),
        )

    def extract(self, rendered_document: str, *, prompt_version: str, effort: str) -> ExtractResult:
        system_prompt = load_prompt(prompt_version)
        self._capture.clear()
        parsed: Extraction | None = None
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=[{"role": "user", "content": rendered_document}],
                output_format=Extraction,
                output_config=OutputConfigParam(effort=_effort(effort)),
            )
            if response.stop_reason == "end_turn":
                parsed = response.parsed_output
            raw = self._capture.body or response.to_dict(mode="json")
        except pydantic.ValidationError:
            # The SDK couldn't parse the text block (refusal text, truncated JSON, ...).
            raw_body = self._capture.body
            if raw_body is None:
                raise ProviderError(
                    Reason.invalid_output, "The response couldn't be read."
                ) from None
            raw = raw_body
        except anthropic.AuthenticationError as error:
            raise ProviderError(
                Reason.auth_error, "The API key was rejected.", status_code=error.status_code
            ) from None
        except anthropic.PermissionDeniedError as error:
            raise ProviderError(
                Reason.auth_error,
                "The API key isn't allowed to use this model.",
                status_code=error.status_code,
            ) from None
        except anthropic.RateLimitError as error:
            raise ProviderError(
                Reason.rate_limited,
                "Rate limited; try again in a minute.",
                status_code=error.status_code,
            ) from None
        except anthropic.BadRequestError as error:
            message = (
                WORKSPACE_HINT
                if "workspace" in str(error.message).lower()
                else "The API rejected the request (400)."
            )
            raise ProviderError(Reason.api_error, message, status_code=error.status_code) from None
        except anthropic.APIStatusError as error:
            raise ProviderError(
                Reason.api_error,
                f"The API returned an error ({error.status_code}).",
                status_code=error.status_code,
            ) from None
        except anthropic.APIConnectionError:
            raise ProviderError(Reason.network_error, "Couldn't reach the Anthropic API.") from None

        return result_from_raw(raw, model=self.model, parsed=parsed)

    def count_input_tokens(self, rendered_document: str, *, prompt_version: str) -> int:
        """For `papertrail record`: estimate the cost before calling."""
        from anthropic.lib._parse._transform import transform_schema  # noqa: PLC0415

        result = self._client.messages.count_tokens(
            model=self.model,
            system=load_prompt(prompt_version),
            messages=[{"role": "user", "content": rendered_document}],
            output_config={
                "format": {"type": "json_schema", "schema": transform_schema(Extraction)}
            },
        )
        return int(result.input_tokens)
