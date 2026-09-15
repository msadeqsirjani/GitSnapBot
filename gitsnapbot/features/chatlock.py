from __future__ import annotations

from typing import Any


def bound_chat_id(config: Any, store: Any) -> str | None:
    return config.telegram_chat_id or store.chat_id()


def is_allowed(incoming: str | int, bound: str | None) -> bool:
    if bound is None or bound == "":
        return True
    return str(incoming) == str(bound)


def should_bind(incoming: str | int, bound: str | None) -> bool:
    """True when this is the first chat and we may store it."""
    return bound is None or bound == ""
