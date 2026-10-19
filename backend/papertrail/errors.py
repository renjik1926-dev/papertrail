"""Error codes and failure reasons (BUILD_PLAN §9), defined once and reused by API, CLI and UI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ErrorCode(StrEnum):
    bad_request = "bad_request"
    forbidden_origin = "forbidden_origin"
    not_found = "not_found"
    job_in_progress = "job_in_progress"
    too_large = "too_large"
    not_a_pdf = "not_a_pdf"
    validation_error = "validation_error"
    internal_error = "internal_error"


HTTP_STATUS: dict[ErrorCode, int] = {
    ErrorCode.bad_request: 400,
    ErrorCode.forbidden_origin: 403,
    ErrorCode.not_found: 404,
    ErrorCode.job_in_progress: 409,
    ErrorCode.too_large: 413,
    ErrorCode.not_a_pdf: 415,
    ErrorCode.validation_error: 422,
    ErrorCode.internal_error: 500,
}

DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.bad_request: "Something was wrong with that request.",
    ErrorCode.forbidden_origin: "This request was blocked for your safety.",
    ErrorCode.not_found: "That document no longer exists.",
    ErrorCode.job_in_progress: "This letter is already being processed.",
    ErrorCode.too_large: "File is larger than 20 MB.",
    ErrorCode.not_a_pdf: "That file isn't a PDF.",
    ErrorCode.validation_error: "Some fields were not valid.",
    ErrorCode.internal_error: "Something went wrong. Details are in the log.",
}


class AppError(Exception):
    """An error with a stable code that the API turns into the shared error shape."""

    def __init__(self, code: ErrorCode, message: str | None = None) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES[code]
        super().__init__(self.message)

    @property
    def status(self) -> int:
        return HTTP_STATUS[self.code]


class Reason(StrEnum):
    """Why a document is unsupported, failed, or waiting."""

    encrypted = "encrypted"
    too_many_pages = "too_many_pages"
    scanned = "scanned"
    parse_timeout = "parse_timeout"
    parse_error = "parse_error"
    truncated = "truncated"
    declined = "declined"
    invalid_output = "invalid_output"
    unexpected_stop = "unexpected_stop"
    auth_error = "auth_error"
    rate_limited = "rate_limited"
    network_error = "network_error"
    api_error = "api_error"
    missing_recording = "missing_recording"
    daily_limit = "daily_limit"


@dataclass(frozen=True)
class ReasonInfo:
    message: str
    next_step: str


REASONS: dict[Reason, ReasonInfo] = {
    Reason.encrypted: ReasonInfo(
        "This PDF is password-protected.",
        "Open it in a PDF viewer, save an unprotected copy, and upload that.",
    ),
    Reason.too_many_pages: ReasonInfo(
        "This PDF has more pages than PaperTrail handles (50).",
        "Upload only the pages of the letter itself.",
    ),
    Reason.scanned: ReasonInfo(
        "This looks like a scanned document, and PaperTrail can't read scans yet.",
        "Use a PDF that has selectable text.",
    ),
    Reason.parse_timeout: ReasonInfo(
        "Reading this PDF took too long, so it was stopped.",
        "The file may be damaged. Try saving it again from a PDF viewer.",
    ),
    Reason.parse_error: ReasonInfo(
        "PaperTrail couldn't read this PDF.",
        "The file may be damaged. Try saving it again from a PDF viewer.",
    ),
    Reason.truncated: ReasonInfo(
        "This letter is too long to process in one pass.",
        "Try uploading fewer pages at a time.",
    ),
    Reason.declined: ReasonInfo(
        "The AI model declined to read this letter.",
        "Check the letter yourself; PaperTrail can't help with this one.",
    ),
    Reason.invalid_output: ReasonInfo(
        "The AI model's answer couldn't be read.",
        "Try again with Retry.",
    ),
    Reason.unexpected_stop: ReasonInfo(
        "The AI model stopped unexpectedly.",
        "Try again with Retry.",
    ),
    Reason.auth_error: ReasonInfo(
        "The Anthropic API rejected the API key.",
        "Check your API key in the .env file, then try again.",
    ),
    Reason.rate_limited: ReasonInfo(
        "The Anthropic API is busy (rate limited).",
        "Try again in a minute.",
    ),
    Reason.network_error: ReasonInfo(
        "PaperTrail couldn't reach the Anthropic API.",
        "Check your internet connection, then try again.",
    ),
    Reason.api_error: ReasonInfo(
        "The Anthropic API returned an error.",
        "Try again later. Details are in the log.",
    ),
    Reason.missing_recording: ReasonInfo(
        "No saved response exists for this letter.",
        "Run `papertrail record` to save one, or use the Claude provider.",
    ),
    Reason.daily_limit: ReasonInfo(
        "Daily limit reached; this letter will be processed tomorrow.",
        "Raise PAPERTRAIL_MAX_DOCS_PER_DAY if you need more.",
    ),
}


WORKSPACE_HINT = (
    "This API key isn't tied to a workspace: create the key inside a workspace, "
    "or set ANTHROPIC_WORKSPACE_ID."
)


def describe(reason: str) -> ReasonInfo:
    try:
        return REASONS[Reason(reason)]
    except ValueError:
        return ReasonInfo("Something went wrong.", "Try again with Retry.")
