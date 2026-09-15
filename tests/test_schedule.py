from pathlib import Path
from types import SimpleNamespace

import pytest

from gitsnapbot.features.schedule import (
    apply_schedule,
    describe_schedule,
    load_schedule,
    parse_clock,
    parse_schedule,
)
from gitsnapbot.store import Store


def test_parse_clock_accepts_hour_or_hhmm() -> None:
    assert parse_clock("9") == (9, 0)
    assert parse_clock("09:30") == (9, 30)
    assert parse_clock("18.45") == (18, 45)


def test_parse_clock_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        parse_clock("24:00")
    with pytest.raises(ValueError):
        parse_clock("noon")


def test_parse_schedule_weekly_slot() -> None:
    parsed = parse_schedule("monday 9:00")
    assert parsed == {"period": "weekly", "weekday": 0, "hour": 9, "minute": 0}


def test_parse_schedule_timezone_and_brief() -> None:
    assert parse_schedule("timezone Asia/Tehran") == {"timezone": "Asia/Tehran"}
    assert parse_schedule("tz UTC") == {"timezone": "UTC"}
    assert parse_schedule("brief on") == {"daily_brief": True}
    assert parse_schedule("brief off") == {"daily_brief": False}


def test_parse_schedule_empty_and_errors() -> None:
    assert parse_schedule("") == {}
    with pytest.raises(ValueError):
        parse_schedule("monday")
    with pytest.raises(ValueError):
        parse_schedule("brief maybe")
    with pytest.raises(ValueError):
        parse_schedule("timezone Not/AZone")


def test_apply_and_load_schedule(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    config = SimpleNamespace(
        digest_period="weekly",
        digest_weekday=0,
        digest_hour=9,
        digest_minute=0,
        digest_timezone="America/Chicago",
        digest_daily_brief=False,
    )
    apply_schedule(
        store,
        {"period": "weekly", "weekday": 2, "hour": 18, "minute": 15, "timezone": "Asia/Tehran"},
    )
    apply_schedule(store, {"daily_brief": True})
    sched = load_schedule(store, config)
    assert sched["weekday"] == 2
    assert sched["hour"] == 18
    assert sched["minute"] == 15
    assert sched["tz_name"] == "Asia/Tehran"
    assert sched["daily_brief"] is True
    text = describe_schedule(sched)
    assert "Wednesday" in text
    assert "18:15" in text
    assert "Daily brief: on" in text
    store.close()
