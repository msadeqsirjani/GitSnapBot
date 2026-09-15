from __future__ import annotations

from datetime import datetime

from gitsnapbot.digest import SECTIONS, digest_is_due
from gitsnapbot.messages import Alert, escape, github_avatar_url, rich_figure


def format_daily_brief(
    items: list[dict[str, str | None]],
    *,
    username: str | None = None,
    next_report: str | None = None,
) -> Alert:
    counts: dict[str, int] = {}
    for item in items:
        kind = str(item.get("kind") or "activity")
        counts[kind] = counts.get(kind, 0) + 1
    n = len(items)
    headline = (
        f"{n} update{'s' if n != 1 else ''} queued for the weekly report"
        if n
        else "No new activity queued yet"
    )
    known = {key for key, _, _ in SECTIONS}
    rows = []
    for kind, icon, title in SECTIONS:
        count = counts.get(kind, 0)
        if count:
            rows.append(f"<tr><th>{icon} {escape(title)}</th><td>{count}</td></tr>")
    other = sum(count for kind, count in counts.items() if kind not in known)
    if other:
        rows.append(f"<tr><th>Other</th><td>{other}</td></tr>")
    rich: list[str] = []
    image_url = github_avatar_url(username) if username else None
    if image_url:
        rich.append(rich_figure(image_url, escape(username or "")))
    rich.append("<h2>Daily brief</h2>")
    rich.append(f"<p>{escape(headline)}.</p>")
    if rows:
        rich.append(f"<table bordered striped compact>{''.join(rows)}</table>")
    if next_report:
        rich.append(f"<p>Next weekly report: {escape(next_report)}</p>")
    plain = ["<b>Daily brief</b>", f"{headline}."]
    if next_report:
        plain.append(f"Next weekly report: {next_report}")
    return Alert(
        kind="brief",
        text="".join(rich),
        fallback="\n".join(plain),
        image_url=image_url,
    )


def brief_is_due(
    now: datetime,
    last_brief: datetime | None,
    *,
    hour: int,
    minute: int,
    tz,
) -> bool:
    return digest_is_due(
        now,
        last_brief,
        period="daily",
        weekday=0,
        hour=hour,
        minute=minute,
        tz=tz,
    )
