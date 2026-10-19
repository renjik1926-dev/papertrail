"""The plain-code verifier: decides what is shown (BUILD_PLAN §8.6, decision D5).

Determinism rule: given the same blocks and the same model output, this produces exactly the
same items, statuses and reasons on any machine on any day. Nothing here reads the clock,
the network or random numbers.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date

from papertrail.extract.schema import Action, Amount, Deadline, Extraction, Sourced, Uncertainty
from papertrail.locate import locate
from papertrail.merge import attach_deadlines
from papertrail.parse.models import Block
from papertrail.parse.normalize import normalize_text
from papertrail.verify.amounts import check_amount_valid, check_amount_value
from papertrail.verify.conflicts import ConflictCandidate, find_conflicts, is_duplicate
from papertrail.verify.dates import check_deadline_date, check_deadline_value, resolve_document_date
from papertrail.verify.injection import check_injection
from papertrail.verify.models import (
    Check,
    CheckResult,
    ItemKind,
    SourceRange,
    VerifiedDocument,
    VerifiedItem,
)
from papertrail.verify.negation import check_negation
from papertrail.verify.quotes import check_quote
from papertrail.verify.status import status_for
from papertrail.verify.text import Concat, concat_blocks

__all__ = ["item_key", "verify_extraction"]


@dataclass
class _Work:
    ref: str
    kind: ItemKind
    source: Sourced
    text: str
    requirement: str = "required"
    condition: str = ""
    matched_norm: str = ""  # normalized matched passage ("" if the quote wasn't found)
    sources: list[SourceRange] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    due_date: str | None = None
    due_rule: str | None = None
    due_calc: str | None = None
    amount_cents: int | None = None
    amount_role: str | None = None
    merged: bool = False

    def block_ids(self, known: set[str]) -> set[str]:
        ids = {s.block_id for s in self.sources}
        return ids | {b for b in self.source.block_ids if b in known}


def item_key(document_sha256: str, kind: str, matched_or_quote_norm: str) -> str:
    """Stable across runs: document hash + kind + normalized matched quote (BUILD_PLAN §8.13)."""
    payload = "\x1f".join((document_sha256, kind, matched_or_quote_norm))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _flatten(extraction: Extraction) -> list[_Work]:
    out: list[_Work] = []

    def add(
        kind: ItemKind,
        source: Sourced,
        text: str,
        requirement: str = "required",
        condition: str = "",
    ) -> None:
        out.append(
            _Work(
                ref=f"i{len(out) + 1}",
                kind=kind,
                source=source,
                text=text.strip(),
                requirement=requirement,
                condition=condition,
            )
        )

    for action in extraction.actions:
        add(
            ItemKind.action,
            action,
            action.text,
            requirement=action.requirement.value,
            condition=action.condition,
        )
    for request in extraction.documents:
        add(
            ItemKind.document,
            request,
            request.text,
            requirement=request.requirement.value,
            condition=request.condition,
        )
    for deadline in extraction.deadlines:
        add(
            ItemKind.deadline,
            deadline,
            deadline.what,
            requirement=deadline.requirement.value,
            condition=deadline.condition,
        )
    for amount in extraction.amounts:
        add(ItemKind.amount, amount, amount.label)
    for contact in extraction.contacts:
        add(ItemKind.contact, contact, f"{contact.label}: {contact.value}")
    for uncertainty in extraction.uncertainties:
        add(ItemKind.uncertainty, uncertainty, uncertainty.issue)
    return out


def verify_extraction(
    extraction: Extraction, blocks: Sequence[Block], *, document_sha256: str
) -> VerifiedDocument:
    ordered = sorted(blocks, key=lambda b: b.seq)
    known = {b.id: b for b in ordered}
    known_ids = set(known)
    seq_of = {b.id: b.seq for b in ordered}
    document = concat_blocks(ordered)
    document_norm = document.norm
    document_date = resolve_document_date(extraction.document_date_text, document_norm)

    work = _flatten(extraction)
    for item in work:
        _check_item(item, known, document, document_norm, document_date)

    _merge_duplicates(work)
    live = [w for w in work if not w.merged]

    conflict_views = [
        ConflictCandidate(
            ref=w.ref,
            kind=w.kind,
            what=w.text,
            due_date=w.due_date,
            amount_role=w.amount_role,
            amount_cents=w.amount_cents,
        )
        for w in live
    ]
    find_conflicts(conflict_views)
    for w, view in zip(live, conflict_views, strict=True):
        w.checks.extend(view.flags)

    _apply_uncertainties(live, known_ids)

    items: list[VerifiedItem] = []
    for w in live:
        key_text = w.matched_norm or normalize_text(w.source.quote).strip()
        items.append(
            VerifiedItem(
                ref=w.ref,
                kind=w.kind,
                text=w.text,
                requirement=w.requirement,
                condition=w.condition,
                quote=w.source.quote,
                due_date=w.due_date,
                due_rule=w.due_rule,
                due_calc=w.due_calc,
                amount_cents=w.amount_cents,
                amount_role=w.amount_role,
                status=status_for(w.checks),
                item_key=item_key(document_sha256, w.kind.value, key_text),
                sources=w.sources,
                rects=locate(w.sources, known),
                checks=w.checks,
            )
        )

    parents = attach_deadlines(items, seq_of)
    items = [i.model_copy(update={"parent_ref": parents.get(i.ref)}) for i in items]
    return VerifiedDocument(
        document_type=extraction.document_type.value,
        document_date=document_date.isoformat() if document_date else None,
        items=items,
    )


def _source_blocks_norm(item: _Work, known: dict[str, Block]) -> str:
    ids = list(
        dict.fromkeys(
            [s.block_id for s in item.sources] or [b for b in item.source.block_ids if b in known]
        )
    )
    return normalize_text(" ".join(known[b].text for b in ids))


def _check_item(
    item: _Work,
    known: dict[str, Block],
    document: Concat,
    document_norm: str,
    document_date: date | None,
) -> None:
    source = item.source
    quote = check_quote(source.quote, source.block_ids, known, document)
    item.checks.extend(quote.checks)
    matched_norm: str | None = None
    if quote.match is not None:
        item.sources = quote.match.source_ranges()
        item.matched_norm = quote.match.matched_norm
        matched_norm = quote.match.widened_norm()

    if isinstance(source, Deadline):
        item.due_rule = source.rule.value
        value_check = check_deadline_value(
            source, matched_norm=matched_norm, document_norm=document_norm
        )
        if value_check is not None:
            item.checks.append(value_check)
        dates = check_deadline_date(
            source, document_date=document_date, document_norm=document_norm
        )
        item.checks.extend(dates.checks)
        item.due_date = dates.due_date.isoformat() if dates.due_date else None
        item.due_calc = dates.due_calc
    elif isinstance(source, Amount):
        item.amount_role = source.role.value
        valid, cents = check_amount_valid(source)
        item.amount_cents = cents
        item.checks.append(valid)
        item.checks.append(
            check_amount_value(
                source, cents, matched_norm=matched_norm, document_norm=document_norm
            )
        )

    blocks_norm = _source_blocks_norm(item, known)
    negation = check_negation(
        is_action=isinstance(source, Action),
        is_owed_amount=isinstance(source, Amount) and source.role.value == "owed",
        item_norm_text=normalize_text(f"{item.text} {source.quote}"),
        source_blocks_norm=blocks_norm,
        document_norm=document_norm,
    )
    if negation is not None:
        item.checks.append(negation)
    item.checks.append(check_injection(normalize_text(source.quote), blocks_norm))


def _merge_duplicates(work: list[_Work]) -> None:
    """V12: same kind, >= 90% quote overlap and same value -> one item with both sources."""
    for index, keep in enumerate(work):
        if keep.merged:
            continue
        for other in work[index + 1 :]:
            if other.merged or other.kind != keep.kind:
                continue
            # Two deadlines (or amounts) in one sentence share a quote but are different items.
            if (keep.due_date, keep.due_calc, keep.amount_cents) != (
                other.due_date,
                other.due_calc,
                other.amount_cents,
            ):
                continue
            if not is_duplicate(keep.sources, other.sources, keep.source.quote, other.source.quote):
                continue
            other.merged = True
            existing = {(s.block_id, s.char_start, s.char_end) for s in keep.sources}
            for s in other.sources:
                if (s.block_id, s.char_start, s.char_end) not in existing:
                    keep.sources.append(s)
            if not any(c.name == "duplicate" for c in keep.checks):
                keep.checks.append(
                    Check(
                        name="duplicate",
                        result=CheckResult.passed,
                        detail="Merged with a duplicate item.",
                    )
                )


def _apply_uncertainties(live: list[_Work], known_ids: set[str]) -> None:
    """V11: an uncertainty whose blocks overlap an item flags that item with the model's issue."""
    uncertainties = [w for w in live if w.kind == ItemKind.uncertainty]
    for item in live:
        if item.kind == ItemKind.uncertainty:
            continue
        item_blocks = item.block_ids(known_ids)
        issues = [
            u.text
            for u in uncertainties
            if isinstance(u.source, Uncertainty) and u.block_ids(known_ids) & item_blocks
        ]
        if issues:
            item.checks.append(
                Check(
                    name="uncertain",
                    result=CheckResult.flag,
                    detail="Model was unsure: " + "; ".join(issues),
                )
            )
