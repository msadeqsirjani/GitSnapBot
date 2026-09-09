from __future__ import annotations

from typing import Any

SOCIAL_EVENT_TYPES = {"WatchEvent", "ForkEvent"}


def actors_from_events(events: list[dict[str, Any]], event_type: str, wanted: int) -> list[str]:
    """Newest-first events feed → that many unique actors of one type."""
    found: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.get("type") != event_type:
            continue
        login = (event.get("actor") or {}).get("login")
        if not login or login in seen:
            continue
        seen.add(login)
        found.append(login)
        if len(found) >= wanted:
            break
    return found
