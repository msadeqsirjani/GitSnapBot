from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from gitsnapbot.messages import (
    Alert,
    escape,
    github_avatar_url,
    github_repo_og_url,
    repo_link,
    rich_figure,
)

WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}

SECTIONS = [
    ("follow", "➕", "New followers"),
    ("unfollow", "➖", "Followers removed"),
    ("deleted", "⚠️", "Deleted accounts"),
    ("star", "⭐", "Stars"),
    ("unstar", "⭐", "Stars removed"),
    ("fork", "🍴", "Forks"),
    ("unfork", "🍴", "Forks removed"),
    ("watch", "👁", "Watchers"),
    ("unwatch", "👁", "Watchers removed"),
    ("issue", "🐛", "Issues"),
    ("comment", "💬", "Comments"),
    ("pr", "🔀", "Pull requests"),
    ("pr_comment", "💬", "Pull request comments"),
    ("review", "🔎", "Reviews"),
    ("review_comment", "💬", "Review comments"),
    ("push", "📦", "Pushes"),
    ("release", "🏷", "Releases"),
    ("member", "👤", "Collaborators"),
    ("notification", "🔔", "Mentions"),
    ("traffic_views", "👁", "Repository views"),
    ("traffic_clones", "📥", "Repository clones"),
    ("create", "＋", "Created"),
    ("delete", "－", "Deleted"),
    ("public", "🌐", "Made public"),
    ("wiki", "📝", "Wiki"),
    ("sponsor", "♥", "Sponsors"),
    ("discussion", "💬", "Discussions"),
    ("discussion_comment", "💬", "Discussion comments"),
    ("commit_comment", "💬", "Commit comments"),
]


def parse_weekday(value: str) -> int:
    key = value.strip().lower()
    if key not in WEEKDAYS:
        raise SystemExit(
            f"DIGEST_WEEKDAY must be one of {', '.join(WEEKDAYS)}, got {value!r}"
        )
    return WEEKDAYS[key]


def last_digest_slot(
    now: datetime,
    *,
    period: str,
    weekday: int,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime:
    local = now.astimezone(tz)
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if period == "daily":
        if candidate > local:
            candidate -= timedelta(days=1)
        return candidate
    days_back = (candidate.weekday() - weekday) % 7
    candidate -= timedelta(days=days_back)
    if candidate > local:
        candidate -= timedelta(days=7)
    return candidate


def next_digest_slot(
    now: datetime,
    *,
    period: str,
    weekday: int,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> datetime:
    last = last_digest_slot(
        now, period=period, weekday=weekday, hour=hour, minute=minute, tz=tz
    )
    delta = timedelta(days=1 if period == "daily" else 7)
    nxt = last + delta
    if nxt <= now.astimezone(tz):
        nxt += delta
    return nxt


def digest_is_due(
    now: datetime,
    last_sent: datetime | None,
    *,
    period: str,
    weekday: int,
    hour: int,
    minute: int,
    tz: ZoneInfo,
) -> bool:
    slot = last_digest_slot(
        now, period=period, weekday=weekday, hour=hour, minute=minute, tz=tz
    )
    if last_sent is None:
        return False
    return last_sent.astimezone(tz) < slot <= now.astimezone(tz)


def format_period(start: datetime, end: datetime) -> str:
    start_local = start
    end_local = end
    if start_local.year == end_local.year and start_local.month == end_local.month:
        return f"{start_local.day}–{end_local.day} {end_local.strftime('%b %Y')}"
    if start_local.year == end_local.year:
        return f"{start_local.day} {start_local.strftime('%b')} – {end_local.day} {end_local.strftime('%b %Y')}"
    return f"{start_local.day} {start_local.strftime('%b %Y')} – {end_local.day} {end_local.strftime('%b %Y')}"


def snapshot_line(label: str, previous: int | None, current: int) -> tuple[str, str]:
    if previous is None:
        html = f"<tr><th>{escape(label)}</th><td><b>{current}</b></td></tr>"
        plain = f"{label}  ·  {current}"
        return html, plain
    delta = current - previous
    if delta == 0:
        change = "unchanged"
    elif delta > 0:
        change = f"+{delta}"
    else:
        change = str(delta)
    html = (
        f"<tr><th>{escape(label)}</th>"
        f"<td>{previous} → <b>{current}</b> ({escape(change)})</td></tr>"
    )
    plain = f"{label}  ·  {previous} → {current} ({change})"
    return html, plain


def top_starred_repos(items: list[dict[str, str | None]], limit: int) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for item in items:
        if item.get("kind") != "star":
            continue
        repo = item.get("repo")
        if repo:
            counts[repo] += 1
    return counts.most_common(limit)


def format_weekly_digest(
    items: list[dict[str, str | None]],
    *,
    period_start: datetime,
    period_end: datetime,
    follower_count: int,
    signature: str,
    max_lines: int,
    star_count: int = 0,
    prev_followers: int | None = None,
    prev_stars: int | None = None,
    top_repo_limit: int = 5,
    username: str | None = None,
    preview: bool = False,
) -> Alert:
    period = format_period(period_start, period_end)
    counts: dict[str, int] = {}
    grouped: dict[str, list[dict[str, str | None]]] = {}
    for item in items:
        kind = str(item.get("kind") or "activity")
        counts[kind] = counts.get(kind, 0) + 1
        grouped.setdefault(kind, []).append(item)

    summary_rows = []
    known = {key for key, _, _ in SECTIONS}
    for kind, icon, title in SECTIONS:
        n = counts.get(kind, 0)
        if n:
            summary_rows.append(f"<tr><th>{icon} {escape(title)}</th><td>{n}</td></tr>")
    other = sum(n for kind, n in counts.items() if kind not in known)
    if other:
        summary_rows.append(f"<tr><th>Other</th><td>{other}</td></tr>")

    follow_html, follow_plain = snapshot_line("Followers", prev_followers, follower_count)
    star_html, star_plain = snapshot_line("Stars", prev_stars, star_count)

    headline = (
        f"{len(items)} update{'s' if len(items) != 1 else ''}"
        if items
        else "No activity this period"
    )
    image_url: str | None = github_avatar_url(username) if username else None
    title = "Activity report (preview)" if preview else "GitHub activity report"
    rich: list[str] = []
    if username:
        rich.append(
            rich_figure(
                github_avatar_url(username),
                f"{escape(username)} · {escape(title)}",
            )
        )
    rich.extend(
        [
            f"<h1>{escape(title)}</h1>",
            f"<p><b>{escape(period)}</b> · {escape(headline)}</p>",
            f"<table bordered striped compact>{follow_html}{star_html}</table>",
        ]
    )
    plain: list[str] = [
        f"<b>{escape(title)}</b>",
        f"{escape(period)} · {headline}",
        follow_plain,
        star_plain,
    ]
    if preview:
        note = "Queue is unchanged. The scheduled report will still be delivered."
        rich.append(f"<p><i>{note}</i></p>")
        plain.append(note)
    if not items:
        rich.append("<p><i>No GitHub activity was recorded during this period.</i></p>")
        plain.append("No GitHub activity was recorded during this period.")
    if summary_rows:
        rich.append(f"<h2>Summary</h2><table bordered striped compact>{''.join(summary_rows)}</table>")

    top = top_starred_repos(items, top_repo_limit)
    if top:
        rows = "".join(
            f"<tr><td>{repo_link(name)}</td><td>+{n}</td></tr>" for name, n in top
        )
        rich.append(rich_figure(github_repo_og_url(top[0][0]), escape(top[0][0])))
        rich.append(f"<h2>Most starred repositories</h2><table bordered striped compact>{rows}</table>")
        plain.append("\n<b>Most starred repositories</b>")
        plain.extend(f"• {name}  +{n}" for name, n in top)
        if image_url is None:
            image_url = github_repo_og_url(top[0][0])

    used = {key for key, _, _ in SECTIONS}
    ordered_kinds = [(k, i, t) for k, i, t in SECTIONS if k in grouped]
    extras = sorted(k for k in grouped if k not in used)
    for kind in extras:
        ordered_kinds.append((kind, "•", kind.replace("_", " ").title()))

    for kind, icon, title in ordered_kinds:
        rows = grouped[kind]
        shown = rows[:max_lines]
        extra = len(rows) - len(shown)
        bullets = []
        plain_lines = []
        for row in shown:
            snippet = row.get("line") or row.get("actor") or row.get("repo") or kind
            bullets.append(f"<li>{snippet}</li>")
            plain_lines.append(f"• {snippet}")
        if extra > 0:
            bullets.append(f"<li><i>…and {extra} additional items</i></li>")
            plain_lines.append(f"…and {extra} additional items")
        rich.append(f"<h2>{icon} {escape(title)} ({len(rows)})</h2><ul>{''.join(bullets)}</ul>")
        plain.append(f"\n{icon} <b>{escape(title)}</b> ({len(rows)})")
        plain.extend(plain_lines)

    actors: list[str] = []
    for item in items:
        actor = item.get("actor")
        if actor and actor not in actors:
            actors.append(actor)
    if len(actors) >= 2:
        collage = "".join(
            f'<img src="{escape(github_avatar_url(login))}"/>' for login in actors[:8]
        )
        rich.append(
            f"<tg-collage>{collage}<figcaption>Accounts in this report</figcaption></tg-collage>"
        )

    footer = escape(signature) if signature else ""
    if footer:
        rich.append(f"<footer>{footer}</footer>")
        plain.append(f"\n<i>{footer}</i>")

    return Alert(
        kind="preview" if preview else "digest",
        text="".join(rich),
        fallback="\n".join(plain),
        image_url=image_url,
    )
