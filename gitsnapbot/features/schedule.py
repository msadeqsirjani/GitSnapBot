from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo

from gitsnapbot.digest import WEEKDAYS

WEEKDAY_NAMES = {index: name.title() for name, index in WEEKDAYS.items()}


def parse_clock(value: str) -> tuple[int, int]:
    raw = value.strip().lower().replace(".", ":")
    if ":" in raw:
        hour_s, minute_s = raw.split(":", 1)
    else:
        hour_s, minute_s = raw, "0"
    try:
        hour = int(hour_s)
        minute = int(minute_s)
    except ValueError as exc:
        raise ValueError("Time must be HH:MM in 24-hour format") from exc
    if hour > 23 or minute > 59 or hour < 0 or minute < 0:
        raise ValueError("Time must be HH:MM in 24-hour format")
    return hour, minute


def parse_schedule(args: str) -> dict[str, Any]:
    """Parse `/when` arguments. Raises ValueError with a user-facing message."""
    text = args.strip()
    if not text:
        return {}
    parts = text.split()
    head = parts[0].lower()
    if head == "brief":
        if len(parts) != 2 or parts[1].lower() not in {"on", "off"}:
            raise ValueError("Use /when brief on  or  /when brief off")
        return {"daily_brief": parts[1].lower() == "on"}
    if head in {"timezone", "tz"}:
        if len(parts) != 2:
            raise ValueError("Use /when timezone Asia/Tehran")
        name = parts[1]
        try:
            ZoneInfo(name)
        except Exception as exc:
            raise ValueError(f"Unknown timezone {name!r}") from exc
        return {"timezone": name}
    weekday = WEEKDAYS.get(head)
    if weekday is None:
        raise ValueError(
            "Use /when monday 9:00, /when timezone Asia/Tehran, or /when brief on"
        )
    if len(parts) < 2:
        raise ValueError("Include a time, for example /when monday 9:00")
    hour, minute = parse_clock(parts[1])
    return {"period": "weekly", "weekday": weekday, "hour": hour, "minute": minute}


def apply_schedule(store: Any, parsed: dict[str, Any]) -> None:
    if "timezone" in parsed:
        store.set_meta("digest_timezone", str(parsed["timezone"]))
    if "weekday" in parsed:
        store.set_meta("digest_weekday", str(int(parsed["weekday"])))
    if "hour" in parsed:
        store.set_meta("digest_hour", str(int(parsed["hour"])))
    if "minute" in parsed:
        store.set_meta("digest_minute", str(int(parsed["minute"])))
    if "period" in parsed:
        store.set_meta("digest_period", str(parsed["period"]))
    if "daily_brief" in parsed:
        store.set_meta("digest_daily_brief", "1" if parsed["daily_brief"] else "0")


def brief_enabled(store: Any, config: Any) -> bool:
    raw = store.get_meta("digest_daily_brief")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(config.digest_daily_brief)


def load_schedule(store: Any, config: Any) -> dict[str, Any]:
    tz_name = store.get_meta("digest_timezone") or config.digest_timezone
    weekday = store.get_int_meta("digest_weekday")
    if weekday is None:
        weekday = config.digest_weekday
    hour = store.get_int_meta("digest_hour")
    if hour is None:
        hour = config.digest_hour
    minute = store.get_int_meta("digest_minute")
    if minute is None:
        minute = config.digest_minute
    period = store.get_meta("digest_period") or config.digest_period
    return {
        "period": period,
        "weekday": weekday,
        "hour": hour,
        "minute": minute,
        "tz_name": tz_name,
        "tz": ZoneInfo(tz_name),
        "daily_brief": brief_enabled(store, config),
    }


def describe_schedule(sched: dict[str, Any]) -> str:
    day = WEEKDAY_NAMES.get(int(sched["weekday"]), "Monday")
    brief = "on" if sched["daily_brief"] else "off"
    return (
        f"Weekly report: {day} {int(sched['hour']):02d}:{int(sched['minute']):02d} "
        f"{sched['tz_name']}\nDaily brief: {brief}"
    )
