from datetime import datetime
from zoneinfo import ZoneInfo

from gitsnapbot.digest import (
    digest_is_due,
    format_period,
    format_weekly_digest,
    last_digest_slot,
    next_digest_slot,
    parse_weekday,
)


TZ = ZoneInfo("UTC")


def test_parse_weekday() -> None:
    assert parse_weekday("Monday") == 0
    assert parse_weekday("sunday") == 6


def test_weekly_slot_before_and_after_monday_nine() -> None:
    monday_eight = datetime(2026, 9, 7, 8, 0, tzinfo=TZ)  # Monday
    monday_ten = datetime(2026, 9, 7, 10, 0, tzinfo=TZ)
    last_before = last_digest_slot(
        monday_eight, period="weekly", weekday=0, hour=9, minute=0, tz=TZ
    )
    last_after = last_digest_slot(
        monday_ten, period="weekly", weekday=0, hour=9, minute=0, tz=TZ
    )
    assert last_before == datetime(2026, 8, 31, 9, 0, tzinfo=TZ)
    assert last_after == datetime(2026, 9, 7, 9, 0, tzinfo=TZ)
    nxt = next_digest_slot(monday_ten, period="weekly", weekday=0, hour=9, minute=0, tz=TZ)
    assert nxt == datetime(2026, 9, 14, 9, 0, tzinfo=TZ)


def test_digest_due_only_after_the_weekly_slot() -> None:
    started = datetime(2026, 9, 9, 12, 0, tzinfo=TZ)  # Wednesday
    monday_report = datetime(2026, 9, 14, 9, 1, tzinfo=TZ)
    assert (
        digest_is_due(
            started,
            started,
            period="weekly",
            weekday=0,
            hour=9,
            minute=0,
            tz=TZ,
        )
        is False
    )
    assert (
        digest_is_due(
            monday_report,
            started,
            period="weekly",
            weekday=0,
            hour=9,
            minute=0,
            tz=TZ,
        )
        is True
    )


def test_weekly_digest_is_one_grouped_report() -> None:
    items = [
        {"kind": "follow", "line": "@a followed you", "actor": "a"},
        {"kind": "follow", "line": "@b followed you", "actor": "b"},
        {"kind": "star", "line": "@c starred me/repo", "actor": "c", "repo": "me/repo"},
    ]
    alert = format_weekly_digest(
        items,
        period_start=datetime(2026, 9, 7, 9, 0, tzinfo=TZ),
        period_end=datetime(2026, 9, 14, 9, 0, tzinfo=TZ),
        follower_count=12,
        signature="GitSnapBot",
        max_lines=20,
    )
    assert alert.kind == "digest"
    assert "Weekly GitSnapBot" in alert.text
    assert "New followers" in alert.text
    assert "Stars" in alert.text
    assert "✦ GitSnapBot" in alert.text
    assert "Top repos" in alert.text
    assert "me/repo" in alert.text
    assert format_period(
        datetime(2026, 9, 7, tzinfo=TZ), datetime(2026, 9, 14, tzinfo=TZ)
    )


def test_week_over_week_and_quiet_week() -> None:
    quiet = format_weekly_digest(
        [],
        period_start=datetime(2026, 9, 7, 9, 0, tzinfo=TZ),
        period_end=datetime(2026, 9, 14, 9, 0, tzinfo=TZ),
        follower_count=43,
        star_count=190,
        prev_followers=40,
        prev_stars=183,
        signature="GitSnapBot",
        max_lines=20,
    )
    assert "quiet week" in quiet.text
    assert "40 → <b>43</b> (+3)" in quiet.text
    assert "183 → <b>190</b> (+7)" in quiet.text
