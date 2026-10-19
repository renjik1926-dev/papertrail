"""Fake provider: a deterministic test double (BUILD_PLAN §8.5).

Two modes:
- scripted: return the given results in order (unit tests, retry and stop-reason tests);
- heuristic (default): build a rough Extraction from the rendered blocks with regular
  expressions, plus one deliberately invented item, so the app can be tried without an API key
  and the verifier visibly rejects something. It is not meant to be accurate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from papertrail.extract.providers.base import ExtractResult
from papertrail.extract.schema import (
    Action,
    Amount,
    AmountRole,
    Contact,
    ContactMethod,
    Deadline,
    DocType,
    DueRule,
    Extraction,
    RelativeUnit,
    Requirement,
)

_TAG = re.compile(r"^\[(p\d+:b\d+)\] ?(.*)$")
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"\b(?:{_MONTHS}) \d{{1,2}}, \d{{4}}\b")
_AMOUNT = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
_PHONE = re.compile(r"\b\d-\d{3}-\d{3}-\d{4}\b")
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
_IMPERATIVE = re.compile(
    r"^(?:please |you must )?(pay|send|call|complete|return|submit|mail)\b", re.I
)
_LETTER_DATE = re.compile(r"\b(?:notice date|statement date|date of this letter|date)\s*:", re.I)

INVENTED_QUOTE = "This sentence was invented by the fake provider and is not in the letter."


def blocks_from_rendered(rendered: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    for line in rendered.splitlines():
        match = _TAG.match(line)
        if match:
            blocks.append((match.group(1), match.group(2)))
        elif blocks and not line.startswith("</document"):
            block_id, text = blocks[-1]
            blocks[-1] = (block_id, f"{text}\n{line}")
    return blocks


def _sentences(text: str) -> Iterable[str]:
    for sentence in _SENTENCE_BREAK.split(text.replace("\n", " ")):
        if sentence.strip():
            yield sentence.strip()


def heuristic_extraction(rendered: str) -> Extraction:
    actions: list[Action] = []
    deadlines: list[Deadline] = []
    amounts: list[Amount] = []
    contacts: list[Contact] = []
    document_date = ""
    for block_id, text in blocks_from_rendered(rendered):
        flat = text.replace("\n", " ")
        if not document_date and _LETTER_DATE.search(flat) and (date := _DATE.search(flat)):
            document_date = date.group(0)
            continue
        for sentence in _sentences(flat):
            ids = [block_id]
            if _IMPERATIVE.search(sentence):
                actions.append(
                    Action(
                        quote=sentence,
                        block_ids=ids,
                        text=sentence,
                        requirement=Requirement.required,
                        condition="",
                    )
                )
            for date in _DATE.findall(sentence):
                deadlines.append(
                    Deadline(
                        quote=sentence,
                        block_ids=ids,
                        what=sentence[:60],
                        date_text=date,
                        relative_amount=0,
                        relative_unit=RelativeUnit.none,
                        anchor_text="",
                        rule=DueRule.unspecified,
                        requirement=Requirement.required,
                        condition="",
                    )
                )
            for amount in _AMOUNT.findall(sentence):
                role = AmountRole.owed if "due" in sentence.lower() else AmountRole.other
                amounts.append(
                    Amount(
                        quote=sentence, block_ids=ids, label="Amount", amount_text=amount, role=role
                    )
                )
            for phone in _PHONE.findall(sentence):
                contacts.append(
                    Contact(
                        quote=sentence,
                        block_ids=ids,
                        label="Phone",
                        method=ContactMethod.phone,
                        value=phone,
                    )
                )
    actions.append(
        Action(
            quote=INVENTED_QUOTE,
            block_ids=["p1:b1"],
            text="(Fake provider) An invented item the verifier should reject",
            requirement=Requirement.required,
            condition="",
        )
    )
    return Extraction(
        document_type=DocType.other,
        document_date_text=document_date,
        actions=actions,
        documents=[],
        deadlines=deadlines,
        amounts=amounts,
        contacts=contacts,
        uncertainties=[],
    )


def result_for(
    extraction: Extraction | None, *, stop_reason: str = "end_turn", model: str = "fake"
) -> ExtractResult:
    raw_text = extraction.model_dump_json() if extraction is not None else ""
    return ExtractResult(
        extraction=extraction if stop_reason == "end_turn" else None,
        stop_reason=stop_reason,
        model=model,
        input_tokens=0,
        output_tokens=0,
        raw={
            "type": "message",
            "model": model,
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": raw_text}],
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
    )


class FakeProvider:
    name = "fake"

    def __init__(
        self, scripted: list[ExtractResult | Exception] | None = None, *, model: str = "fake"
    ) -> None:
        self.model = model
        self._scripted = list(scripted) if scripted is not None else None
        self.calls: list[tuple[str, str]] = []  # (prompt_version, effort) per call

    def extract(self, rendered_document: str, *, prompt_version: str, effort: str) -> ExtractResult:
        self.calls.append((prompt_version, effort))
        if self._scripted is None:
            return result_for(heuristic_extraction(rendered_document), model=self.model)
        if not self._scripted:
            raise AssertionError("FakeProvider ran out of scripted results")
        nxt = self._scripted.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt
