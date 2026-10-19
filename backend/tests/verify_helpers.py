"""Build small synthetic documents (blocks with words) for verifier tests."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from papertrail.extract.schema import (
    Action,
    Amount,
    AmountRole,
    Contact,
    ContactMethod,
    Deadline,
    DocType,
    DocumentRequest,
    DueRule,
    Extraction,
    RelativeUnit,
    Requirement,
    Uncertainty,
)
from papertrail.parse.models import Block, Word


def make_block(
    block_id: str, text: str, *, seq: int, page_no: int = 1, top: float = 100.0
) -> Block:
    """Words get simple synthetic boxes: 6 pt per character, 12 pt line height."""
    words: list[Word] = []
    offset = 0
    for line_no, line in enumerate(text.split("\n")):
        x = 72.0
        for word_text in line.split(" "):
            if word_text:
                words.append(
                    Word(
                        text=word_text,
                        char_start=offset,
                        char_end=offset + len(word_text),
                        x0=x,
                        top=top + 14 * line_no,
                        x1=x + 6 * len(word_text),
                        bottom=top + 14 * line_no + 12,
                    )
                )
            offset += len(word_text) + 1
            x += 6 * (len(word_text) + 1)
    return Block(
        id=block_id,
        page_no=page_no,
        seq=seq,
        text=text,
        x0=min(w.x0 for w in words),
        top=min(w.top for w in words),
        x1=max(w.x1 for w in words),
        bottom=max(w.bottom for w in words),
        words=tuple(words),
    )


def make_blocks(texts: Sequence[str]) -> list[Block]:
    return [
        make_block(f"p1:b{i}", t, seq=i, top=100.0 + 40 * i) for i, t in enumerate(texts, start=1)
    ]


def extraction(**kinds: Any) -> Extraction:
    base: dict[str, Any] = {
        "document_type": DocType.other,
        "document_date_text": "",
        "actions": [],
        "documents": [],
        "deadlines": [],
        "amounts": [],
        "contacts": [],
        "uncertainties": [],
    }
    base.update(kinds)
    return Extraction(**base)


def action(quote: str, ids: list[str], text: str = "Do it", **kw: Any) -> Action:
    return Action(
        quote=quote,
        block_ids=ids,
        text=text,
        requirement=kw.get("requirement", Requirement.required),
        condition=kw.get("condition", ""),
    )


def document(quote: str, ids: list[str], text: str = "A document") -> DocumentRequest:
    return DocumentRequest(
        quote=quote, block_ids=ids, text=text, requirement=Requirement.required, condition=""
    )


def deadline(
    quote: str,
    ids: list[str],
    *,
    what: str = "Respond",
    date_text: str = "",
    amount: int = 0,
    unit: RelativeUnit = RelativeUnit.none,
    anchor: str = "",
) -> Deadline:
    return Deadline(
        quote=quote,
        block_ids=ids,
        what=what,
        date_text=date_text,
        relative_amount=amount,
        relative_unit=unit,
        anchor_text=anchor,
        rule=DueRule.unspecified,
        requirement=Requirement.required,
        condition="",
    )


def amount(
    quote: str, ids: list[str], amount_text: str, role: AmountRole = AmountRole.owed
) -> Amount:
    return Amount(
        quote=quote, block_ids=ids, label="Amount due", amount_text=amount_text, role=role
    )


def contact(quote: str, ids: list[str], value: str) -> Contact:
    return Contact(
        quote=quote, block_ids=ids, label="Office", method=ContactMethod.phone, value=value
    )


def uncertainty(quote: str, ids: list[str], issue: str) -> Uncertainty:
    return Uncertainty(quote=quote, block_ids=ids, issue=issue)
