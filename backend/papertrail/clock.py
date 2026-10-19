"""Anything that needs "now" or "today" takes a Clock, so tests never depend on the real date."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware datetime in the local timezone."""
        ...


class RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC).astimezone()


class FixedClock:
    """A clock that only moves when a test moves it."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._at = at

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta


def utc_iso(moment: datetime) -> str:
    """ISO 8601 UTC string used for every stored timestamp."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def local_today(clock: Clock) -> date:
    return clock.now().date()


def local_midnight_after(clock: Clock) -> datetime:
    """The start of the next local calendar day."""
    now = clock.now()
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, datetime.min.time(), tzinfo=now.tzinfo)


def local_day_start_utc(clock: Clock) -> str:
    """Start of the current local day, as a stored-format UTC timestamp."""
    now = clock.now()
    start = datetime.combine(now.date(), datetime.min.time(), tzinfo=now.tzinfo)
    return utc_iso(start)
