"""What the verifier produces: items with sources, rectangles, checks and a status."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ItemKind(StrEnum):
    action = "action"
    document = "document"
    deadline = "deadline"
    amount = "amount"
    contact = "contact"
    uncertainty = "uncertainty"


class CheckResult(StrEnum):
    passed = "pass"
    flag = "flag"
    fail = "fail"


class ItemStatus(StrEnum):
    verified = "verified"
    needs_review = "needs_review"
    rejected = "rejected"


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Check(Model):
    name: str
    result: CheckResult
    detail: str


class SourceRange(Model):
    block_id: str
    char_start: int
    char_end: int


class Rect(Model):
    page_no: int
    x0: float
    top: float
    x1: float
    bottom: float


class VerifiedItem(Model):
    ref: str  # id within one run ("i3"), used for parent links before rows exist
    kind: ItemKind
    text: str
    requirement: str = "required"
    condition: str = ""
    quote: str
    due_date: str | None = None
    due_rule: str | None = None
    due_calc: str | None = None
    amount_cents: int | None = None
    amount_role: str | None = None
    parent_ref: str | None = None
    status: ItemStatus
    item_key: str
    sources: list[SourceRange]
    rects: list[Rect]
    checks: list[Check]


class VerifiedDocument(Model):
    document_type: str
    document_date: str | None
    items: list[VerifiedItem]
