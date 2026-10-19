"""Combine check results into a status (BUILD_PLAN §8.6)."""

from __future__ import annotations

from collections.abc import Iterable

from papertrail.verify.models import Check, CheckResult, ItemStatus


def status_for(checks: Iterable[Check]) -> ItemStatus:
    """Any fail -> rejected; otherwise any flag -> needs_review; otherwise verified."""
    results = {check.result for check in checks}
    if CheckResult.fail in results:
        return ItemStatus.rejected
    if CheckResult.flag in results:
        return ItemStatus.needs_review
    return ItemStatus.verified


def reasons(checks: Iterable[Check]) -> list[str]:
    """Human-readable reasons for anything that isn't a pass, fails first."""
    ordered = sorted(
        (c for c in checks if c.result != CheckResult.passed),
        key=lambda c: 0 if c.result == CheckResult.fail else 1,
    )
    return [c.detail for c in ordered]
