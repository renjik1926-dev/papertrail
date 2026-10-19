"""Attach deadlines to actions (BUILD_PLAN §8.7).

A deadline attaches to an action when they share a block or their quote spans overlap.
An action gets at most one deadline; ties go to the closest span.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from papertrail.verify.models import ItemKind, SourceRange, VerifiedItem


def _position(sources: Sequence[SourceRange], seq_of: Mapping[str, int]) -> tuple[int, int]:
    if not sources:
        return (10**9, 0)
    first = min(sources, key=lambda s: (seq_of.get(s.block_id, 10**9), s.char_start))
    return (seq_of.get(first.block_id, 10**9), first.char_start)


def attach_deadlines(items: Sequence[VerifiedItem], seq_of: Mapping[str, int]) -> dict[str, str]:
    """Return {deadline_ref: action_ref}."""
    actions = [i for i in items if i.kind == ItemKind.action and i.sources]
    deadlines = [i for i in items if i.kind == ItemKind.deadline and i.sources]
    pairs: list[tuple[int, int, str, str]] = []
    for deadline in deadlines:
        d_blocks = {s.block_id for s in deadline.sources}
        d_seq, d_char = _position(deadline.sources, seq_of)
        for action in actions:
            if not d_blocks & {s.block_id for s in action.sources}:
                continue
            a_seq, a_char = _position(action.sources, seq_of)
            distance = abs(d_seq - a_seq) * 100_000 + abs(d_char - a_char)
            pairs.append((distance, len(pairs), deadline.ref, action.ref))
    attached: dict[str, str] = {}
    used_actions: set[str] = set()
    for _distance, _order, deadline_ref, action_ref in sorted(pairs):
        if deadline_ref in attached or action_ref in used_actions:
            continue
        attached[deadline_ref] = action_ref
        used_actions.add(action_ref)
    return attached
