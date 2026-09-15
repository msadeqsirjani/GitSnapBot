from datetime import datetime
from zoneinfo import ZoneInfo

from gitsnapbot.features.brief import brief_is_due, format_daily_brief

TZ = ZoneInfo("UTC")


def test_daily_brief_summarizes_queue() -> None:
    alert = format_daily_brief(
        [
            {"kind": "follow", "actor": "a"},
            {"kind": "follow", "actor": "b"},
            {"kind": "star", "actor": "c", "repo": "me/repo"},
        ],
        username="octocat",
        next_report="Mon 21 Sep 2026 09:00 UTC",
    )
    assert alert.kind == "brief"
    assert "3 updates queued" in alert.text
    assert "New followers" in alert.text
    assert "octocat.png" in (alert.image_url or "")
    assert "Next weekly report" in alert.text


def test_daily_brief_empty_queue() -> None:
    alert = format_daily_brief([])
    assert "No new activity queued yet" in alert.text


def test_brief_is_due_after_daily_slot() -> None:
    last = datetime(2026, 9, 14, 9, 0, tzinfo=TZ)
    before = datetime(2026, 9, 15, 8, 59, tzinfo=TZ)
    after = datetime(2026, 9, 15, 9, 1, tzinfo=TZ)
    assert brief_is_due(before, last, hour=9, minute=0, tz=TZ) is False
    assert brief_is_due(after, last, hour=9, minute=0, tz=TZ) is True
