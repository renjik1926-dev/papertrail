"""Request and response models for every endpoint, so the OpenAPI schema (and the generated
TypeScript types) fully describe the API (BUILD_PLAN §9)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(Out):
    code: str
    message: str


class ErrorOut(Out):
    error: ErrorBody


class HealthOut(Out):
    ok: bool
    version: str
    worker: str


class PageOut(Out):
    page_no: int
    width: float
    height: float


class RunSummary(Out):
    id: str
    provider: str
    model: str
    prompt_version: str
    effort: str
    status: str
    stop_reason: str | None
    error: str | None
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: float | None
    duration_ms: int | None
    started_at: str
    finished_at: str | None


class DocumentOut(Out):
    id: str
    filename: str
    page_count: int
    status: Literal[
        "queued", "parsing", "extracting", "verifying", "ready", "failed", "unsupported"
    ]
    status_detail: str
    status_message: str | None = Field(description="Plain-language reason for status_detail")
    next_step: str | None
    document_type: str
    document_date: str | None
    current_run_id: str | None
    created_at: str
    updated_at: str


class DocumentDetailOut(DocumentOut):
    pages: list[PageOut]
    current_run: RunSummary | None
    last_run: RunSummary | None
    job_active: bool


class CheckOut(Out):
    name: str
    result: Literal["pass", "flag", "fail"]
    detail: str


class SourceOut(Out):
    block_id: str
    char_start: int
    char_end: int


class RectOut(Out):
    page_no: int
    x0: float
    top: float
    x1: float
    bottom: float


class ItemOriginal(Out):
    text: str
    due_date: str | None
    amount_cents: int | None
    requirement: str
    condition: str


ItemKindOut = Literal["action", "document", "deadline", "amount", "contact", "uncertainty"]


class ItemOut(Out):
    id: str
    kind: ItemKindOut
    text: str
    requirement: Literal["required", "optional", "conditional"]
    condition: str
    quote: str
    due_date: str | None
    due_rule: str | None
    due_calc: str | None
    amount_cents: int | None
    amount_role: str | None
    parent_item_id: str | None
    status: Literal["verified", "needs_review", "rejected"]
    review_state: Literal["none", "accepted", "edited", "dismissed"]
    item_key: str
    position: int = Field(description="Reading-order position of the first source in the letter")
    page_no: int | None
    sources: list[SourceOut]
    rects: list[RectOut]
    checks: list[CheckOut]
    reasons: list[str] = Field(description="Why the item is flagged or rejected, worst first")
    original: ItemOriginal | None = Field(description="The model's version, if the user edited it")


class NoteOut(Out):
    id: str
    text: str
    quote: str


class LostItemOut(Out):
    id: str
    kind: ItemKindOut
    text: str
    review_state: str


class ItemsOut(Out):
    run_id: str | None
    items: list[ItemOut]
    notes: list[NoteOut] = Field(description="Model uncertainties that match no item")
    no_longer_found: list[LostItemOut] = Field(
        description="Items reviewed in an earlier run that the current run didn't find again"
    )


class ItemChanges(BaseModel):
    """Only these fields can be edited; the quote and sources cannot."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, min_length=1, max_length=500)
    due_date: date | None = None
    amount_cents: int | None = Field(default=None, ge=0, le=10**12)
    requirement: Literal["required", "optional", "conditional"] | None = None
    condition: str | None = Field(default=None, max_length=500)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["accept", "edit", "dismiss", "restore"]
    changes: ItemChanges = Field(default_factory=ItemChanges)


class SettingsOut(Out):
    privacy_notice_ack: bool


class SettingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str = Field(max_length=100)
