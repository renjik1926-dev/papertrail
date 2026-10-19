"""The model's output schema (BUILD_PLAN §8.5).

Flat, every field required, no nullable fields: an empty string or 0 means "not applicable".
Enum values are lowercase snake_case, and each enum field lowercases its input first,
because structured outputs don't guarantee enum capitalization.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


def _lower(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Requirement(StrEnum):
    required = "required"
    optional = "optional"
    conditional = "conditional"


class DueRule(StrEnum):
    received_by = "received_by"
    postmarked_by = "postmarked_by"
    on_or_before = "on_or_before"
    unspecified = "unspecified"


class RelativeUnit(StrEnum):
    none = "none"
    calendar_days = "calendar_days"
    business_days = "business_days"
    weeks = "weeks"
    months = "months"


class AmountRole(StrEnum):
    owed = "owed"
    charged = "charged"
    paid_by_insurer = "paid_by_insurer"
    balance = "balance"
    refund = "refund"
    other = "other"


class ContactMethod(StrEnum):
    phone = "phone"
    email = "email"
    mail = "mail"
    website = "website"
    in_person = "in_person"


class DocType(StrEnum):
    tax = "tax"
    government = "government"
    insurance = "insurance"
    medical_bill = "medical_bill"
    university = "university"
    legal = "legal"
    other = "other"


class Sourced(Strict):
    quote: str  # copied exactly from the blocks
    block_ids: list[str]  # e.g. ["p2:b14"]


class Action(Sourced):
    text: str  # plain-language instruction
    requirement: Requirement
    condition: str  # "" if none

    _lower_requirement = field_validator("requirement", mode="before")(_lower)


class DocumentRequest(Sourced):
    text: str  # what to send, e.g. "Signed statement"
    requirement: Requirement
    condition: str

    _lower_requirement = field_validator("requirement", mode="before")(_lower)


class Deadline(Sourced):
    what: str  # what is due
    date_text: str  # exact date text from the letter; "" if relative
    relative_amount: int  # e.g. 60; 0 if not relative
    relative_unit: RelativeUnit
    anchor_text: str  # e.g. "the date of this notice"; "" if none
    rule: DueRule
    requirement: Requirement
    condition: str

    _lower_enums = field_validator("relative_unit", "rule", "requirement", mode="before")(_lower)


class Amount(Sourced):
    label: str  # as labeled in the letter, e.g. "Amount due"
    amount_text: str  # exact text, e.g. "$1,240.00"
    role: AmountRole

    _lower_role = field_validator("role", mode="before")(_lower)


class Contact(Sourced):
    label: str  # e.g. "Customer service"
    method: ContactMethod
    value: str  # number, address, URL as written

    _lower_method = field_validator("method", mode="before")(_lower)


class Uncertainty(Sourced):
    issue: str  # what the model was unsure about


class Extraction(Strict):
    document_type: DocType
    document_date_text: str  # exact text of the letter's date; "" if none
    actions: list[Action]
    documents: list[DocumentRequest]
    deadlines: list[Deadline]
    amounts: list[Amount]
    contacts: list[Contact]
    uncertainties: list[Uncertainty]

    _lower_type = field_validator("document_type", mode="before")(_lower)
