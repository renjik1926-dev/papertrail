"""V8 conflicts and V12 duplicates (BUILD_PLAN §8.6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from papertrail.parse.normalize import normalize_text
from papertrail.verify.models import Check, CheckResult, ItemKind, SourceRange

SAME_WHAT_SCORE = 90
DUPLICATE_OVERLAP = 0.90


@dataclass
class ConflictCandidate:
    ref: str
    kind: ItemKind
    what: str  # deadlines: the `what`; amounts: unused
    due_date: str | None
    amount_role: str | None
    amount_cents: int | None
    flags: list[Check] = field(default_factory=list)


def _cents(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def find_conflicts(items: Sequence[ConflictCandidate]) -> None:
    """Add a `conflicts` flag to both sides of every conflicting pair."""
    deadlines = [i for i in items if i.kind == ItemKind.deadline and i.due_date]
    for index, a in enumerate(deadlines):
        for b in deadlines[index + 1 :]:
            same_what = (
                fuzz.ratio(normalize_text(a.what), normalize_text(b.what)) >= SAME_WHAT_SCORE
            )
            if same_what and a.due_date != b.due_date:
                a.flags.append(_conflict(f"Another deadline for the same thing says {b.due_date}."))
                b.flags.append(_conflict(f"Another deadline for the same thing says {a.due_date}."))
    owed = [
        i
        for i in items
        if i.kind == ItemKind.amount and i.amount_role == "owed" and i.amount_cents is not None
    ]
    for index, a in enumerate(owed):
        for b in owed[index + 1 :]:
            if a.amount_cents != b.amount_cents:
                assert a.amount_cents is not None and b.amount_cents is not None
                a.flags.append(_conflict(f"The letter also says {_cents(b.amount_cents)} is owed."))
                b.flags.append(_conflict(f"The letter also says {_cents(a.amount_cents)} is owed."))


def _conflict(detail: str) -> Check:
    return Check(name="conflicts", result=CheckResult.flag, detail=detail)


def _intervals(sources: Sequence[SourceRange]) -> dict[str, list[tuple[int, int]]]:
    out: dict[str, list[tuple[int, int]]] = {}
    for source in sources:
        out.setdefault(source.block_id, []).append((source.char_start, source.char_end))
    return out


def span_overlap(a: Sequence[SourceRange], b: Sequence[SourceRange]) -> float:
    """Shared characters / the shorter span's length (0..1)."""
    total_a = sum(s.char_end - s.char_start for s in a)
    total_b = sum(s.char_end - s.char_start for s in b)
    if not total_a or not total_b:
        return 0.0
    shared = 0
    intervals_b = _intervals(b)
    for block_id, ranges in _intervals(a).items():
        for start_a, end_a in ranges:
            for start_b, end_b in intervals_b.get(block_id, []):
                shared += max(0, min(end_a, end_b) - max(start_a, start_b))
    return shared / min(total_a, total_b)


def is_duplicate(
    a_sources: Sequence[SourceRange], b_sources: Sequence[SourceRange], a_quote: str, b_quote: str
) -> bool:
    if a_sources and b_sources:
        return span_overlap(a_sources, b_sources) >= DUPLICATE_OVERLAP
    return fuzz.ratio(normalize_text(a_quote), normalize_text(b_quote)) >= DUPLICATE_OVERLAP * 100
