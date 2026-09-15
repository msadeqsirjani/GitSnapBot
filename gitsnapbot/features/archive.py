from __future__ import annotations

from typing import Any

from gitsnapbot.messages import Alert


def save_report(store: Any, alert: Alert) -> None:
    store.save_last_report(alert.text, alert.fallback, alert.image_url)


def load_report(store: Any) -> Alert | None:
    row = store.last_report()
    if not row or not row.get("text"):
        return None
    return Alert(
        kind="last",
        text=str(row["text"]),
        fallback=row.get("fallback"),
        image_url=row.get("image_url"),
    )
