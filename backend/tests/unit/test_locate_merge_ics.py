from datetime import UTC, datetime

from icalendar import Calendar

from papertrail.export.ics import build_calendar
from papertrail.locate import locate, select_words
from papertrail.verify.models import SourceRange
from tests.verify_helpers import make_block


def test_locate_one_rect_per_line_with_padding() -> None:
    block = make_block("p1:b1", "first line here\nsecond line here", seq=1, top=100.0)
    rects = locate([SourceRange(block_id="p1:b1", char_start=6, char_end=22)], {"p1:b1": block})
    assert len(rects) == 2
    assert rects[0].top == 99.0  # 1 pt padding
    assert rects[1].top == 113.0


def test_select_words_overlapping_span() -> None:
    block = make_block("p1:b1", "alpha beta gamma", seq=1)
    assert [w.text for w in select_words(block, 3, 8)] == ["alpha", "beta"]


def item(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": "deadline",
        "status": "verified",
        "review_state": "none",
        "due_date": "2027-01-01",
        "due_calc": "60 calendar days from 2026-11-02 = 2027-01-01",
        "item_key": "abc123",
        "text": "Respond if you disagree",
        "quote": "respond within 60 days",
        "rects": [{"page_no": 2}],
    }
    base.update(overrides)
    return base


def test_ics_event_with_two_reminders() -> None:
    body, skipped = build_calendar(
        [
            item(),
            item(due_date=None, item_key="nodate"),
            item(review_state="dismissed", item_key="gone"),
        ],
        document_name="notice.pdf",
        stamp=datetime(2026, 10, 19, tzinfo=UTC),
    )
    assert skipped == 1
    calendar = Calendar.from_ical(body)
    events = list(calendar.walk("VEVENT"))
    assert len(events) == 1
    event = events[0]
    assert str(event["uid"]) == "abc123@papertrail.local"
    assert event.decoded("dtstart").isoformat() == "2027-01-01"
    assert event.decoded("dtend").isoformat() == "2027-01-02"
    assert str(event["summary"]) == "Due: Respond if you disagree"
    description = str(event["description"])
    assert "Page 2" in description and "Calculated:" in description
    triggers = sorted(a.decoded("trigger").days for a in event.walk("VALARM"))
    assert triggers == [-7, -1]


def test_ics_marks_items_that_need_review() -> None:
    body, _ = build_calendar(
        [item(status="needs_review")],
        document_name="n.pdf",
        stamp=datetime(2026, 10, 19, tzinfo=UTC),
    )
    assert "(needs review)" in str(Calendar.from_ical(body).walk("VEVENT")[0]["description"])
