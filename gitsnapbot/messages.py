from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


@dataclass(slots=True)
class Alert:
    kind: str
    text: str
    url: str | None = None
    group: str | None = None
    actor: str | None = None
    fallback: str | None = None
    line: str | None = None
    repo: str | None = None
    image_url: str | None = None


def card(
    icon: str,
    title: str,
    *,
    body: str = "",
    quote: str | None = None,
    fields: list[tuple[str, str]] | None = None,
    footer: str | None = None,
) -> tuple[str, str]:
    """Build a Rich Message HTML card plus a sendMessage fallback."""
    rich: list[str] = [f"<h2>{icon} {escape(title)}</h2>"]
    plain: list[str] = [f"{icon}  <b>{escape(title)}</b>"]
    if body:
        rich.append(f"<p>{body}</p>")
        plain.append(body)
    if quote:
        rich.append(f"<blockquote>{quote}</blockquote>")
        plain.append(quote)
    if fields:
        rows = "".join(f"<tr><th>{escape(key)}</th><td>{value}</td></tr>" for key, value in fields)
        rich.append(f"<table bordered striped compact>{rows}</table>")
        for key, value in fields:
            plain.append(f"{escape(key)}  ·  {value}")
    if footer:
        rich.append(f"<footer>{footer}</footer>")
        plain.append(f"<i>{footer}</i>")
    return "".join(rich), "\n".join(plain)


def signed(alert: Alert, signature: str) -> Alert:
    if not signature:
        return alert
    mark = escape(signature)
    alert.text = f"{alert.text}<footer>{mark}</footer>"
    if alert.fallback:
        alert.fallback = f"{alert.fallback}\n<i>{mark}</i>"
    else:
        alert.fallback = f"{alert.text}\n<i>{mark}</i>"
    return alert


def alert_card(
    kind: str,
    icon: str,
    title: str,
    *,
    body: str = "",
    quote: str | None = None,
    fields: list[tuple[str, str]] | None = None,
    footer: str | None = None,
    url: str | None = None,
    actor: str | None = None,
    group: str | None = None,
    line: str | None = None,
    repo: str | None = None,
) -> Alert:
    text, fallback = card(icon, title, body=body, quote=quote, fields=fields, footer=footer)
    return Alert(
        kind=kind,
        text=text,
        fallback=fallback,
        url=url,
        actor=actor,
        group=group,
        line=line or body or quote,
        repo=repo,
    )


NOISY_ISSUE_ACTIONS = {"edited", "unlabeled"}
NOISY_PR_ACTIONS = {"edited", "synchronize", "unlabeled"}
SKIP_EVENT_TYPES = {"StatusEvent"}

NOTIFICATION_REASONS = {
    "mention": "You were mentioned.",
    "assign": "You were assigned.",
    "review_requested": "Your review was requested.",
    "team_mention": "Your team was mentioned.",
    "invitation": "You were invited.",
    "security_alert": "A security alert was issued.",
    "approval_requested": "Your approval was requested.",
    "ci_activity": None,
    "subscribed": None,
}

GENERIC_KIND = {
    "WatchEvent": "star",
    "ForkEvent": "fork",
    "IssuesEvent": "issue",
    "IssueCommentEvent": "comment",
    "PullRequestEvent": "pr",
    "PullRequestReviewEvent": "review",
    "PullRequestReviewCommentEvent": "review_comment",
    "PushEvent": "push",
    "CreateEvent": "create",
    "DeleteEvent": "delete",
    "ReleaseEvent": "release",
    "MemberEvent": "member",
    "PublicEvent": "public",
    "CommitCommentEvent": "commit_comment",
    "GollumEvent": "wiki",
    "SponsorshipEvent": "sponsor",
    "DiscussionEvent": "discussion",
    "DiscussionCommentEvent": "discussion_comment",
}


def escape(text: str | None) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def user_link(login: str) -> str:
    safe = escape(login)
    return f'<a href="https://github.com/{safe}">@{safe}</a>'


def repo_link(full_name: str) -> str:
    safe = escape(full_name)
    return f'<a href="https://github.com/{safe}">{safe}</a>'


def github_avatar_url(login: str) -> str:
    return f"https://github.com/{quote(login, safe='')}.png?size=460"


def github_repo_og_url(repo: str) -> str:
    return f"https://opengraph.githubassets.com/gitsnapbot/{quote(repo, safe='/')}"


def rich_figure(url: str, caption: str | None = None) -> str:
    img = f'<img src="{escape(url)}"/>'
    if not caption:
        return img
    return f"<figure>{img}<figcaption>{caption}</figcaption></figure>"


def html_url_from_api(url: str | None) -> str | None:
    if not url:
        return None
    html = url.replace("https://api.github.com/repos/", "https://github.com/")
    html = html.replace("/pulls/", "/pull/")
    html = html.replace("/comments/", "#issuecomment-")
    return html


def short_body(text: str | None, limit: int = 180) -> str:
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) > limit:
        collapsed = collapsed[: limit - 1] + "…"
    return escape(collapsed)


def parse_time(value: str | None) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return escape(value)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def actor_login(event: dict[str, Any]) -> str:
    actor = event.get("actor") or {}
    return actor.get("login") or "unknown"


def repo_name(event: dict[str, Any]) -> str:
    repo = event.get("repo") or {}
    return repo.get("name") or "unknown/unknown"


def event_url(event: dict[str, Any]) -> str:
    return f"https://github.com/{repo_name(event)}"


def is_relevant_event(event: dict[str, Any], owners: set[str]) -> bool:
    event_type = event.get("type") or ""
    if event_type in SKIP_EVENT_TYPES:
        return False
    name = repo_name(event)
    owner = name.split("/", 1)[0].lower()
    return owner in owners


def format_follow(login: str, total: int) -> Alert:
    return alert_card(
        "follow",
        "➕",
        "New follower",
        body=f"{user_link(login)} started following you.",
        fields=[("Followers", str(total))],
        url=f"https://github.com/{login}",
        actor=login,
        group="follow",
    )


def format_unfollow(login: str, total: int) -> Alert:
    return alert_card(
        "unfollow",
        "➖",
        "Follower removed",
        body=f"{user_link(login)} is no longer following you.",
        fields=[("Followers", str(total))],
        url=f"https://github.com/{login}",
        actor=login,
        group="unfollow",
    )


def format_deleted(login: str, total: int) -> Alert:
    return alert_card(
        "deleted",
        "⚠️",
        "Account deleted",
        body=f"The GitHub account {user_link(login)} is no longer available.",
        fields=[("Followers", str(total))],
        url=f"https://github.com/{login}",
        actor=login,
        group="deleted",
    )


def format_star(login: str, repo: str, total: int | None = None) -> Alert:
    fields = [("Repository", repo_link(repo))]
    if total is not None:
        fields.append(("Stars", str(total)))
    return alert_card(
        "star",
        "⭐",
        "New star",
        body=f"{user_link(login)} starred {repo_link(repo)}.",
        fields=fields,
        url=f"https://github.com/{repo}",
        actor=login,
        group=f"star:{repo}",
        repo=repo,
    )


def format_unstar(login: str, repo: str, total: int | None = None) -> Alert:
    fields = [("Repository", repo_link(repo))]
    if total is not None:
        fields.append(("Stars", str(total)))
    return alert_card(
        "unstar",
        "⭐",
        "Star removed",
        body=f"{user_link(login)} removed a star from {repo_link(repo)}.",
        fields=fields,
        url=f"https://github.com/{repo}",
        actor=login,
        group=f"unstar:{repo}",
    )


def format_new_fork(login: str, repo: str, total: int | None = None) -> Alert:
    fields = [("Repository", repo_link(repo))]
    if total is not None:
        fields.append(("Forks", str(total)))
    return alert_card(
        "fork",
        "🍴",
        "New fork",
        body=f"{user_link(login)} forked {repo_link(repo)}.",
        fields=fields,
        url=f"https://github.com/{login}/{repo.split('/', 1)[-1]}",
        actor=login,
        group=f"fork:{repo}",
    )


def format_unfork(login: str, repo: str, total: int | None = None) -> Alert:
    fields = [("Repository", repo_link(repo))]
    if total is not None:
        fields.append(("Forks", str(total)))
    return alert_card(
        "unfork",
        "🍴",
        "Fork removed",
        body=f"{user_link(login)} deleted their fork of {repo_link(repo)}.",
        fields=fields,
        url=f"https://github.com/{repo}",
        actor=login,
        group=f"unfork:{repo}",
    )


def format_star_count_delta(repo: str, delta: int, total: int) -> Alert:
    if delta > 0:
        kind, icon, title = "star", "⭐", f"{delta} new star{'s' if delta != 1 else ''}"
    else:
        n = abs(delta)
        kind, icon, title = "unstar", "⭐", f"{n} star{'s' if n != 1 else ''} removed"
    return alert_card(
        kind,
        icon,
        title,
        body=repo_link(repo),
        fields=[("Stars", str(total))],
        url=f"https://github.com/{repo}",
        group=f"{kind}:{repo}",
    )


def format_fork_count_delta(repo: str, delta: int, total: int) -> Alert:
    if delta > 0:
        kind, icon, title = "fork", "🍴", f"{delta} new fork{'s' if delta != 1 else ''}"
    else:
        n = abs(delta)
        kind, icon, title = "unfork", "🍴", f"{n} fork{'s' if n != 1 else ''} removed"
    return alert_card(
        kind,
        icon,
        title,
        body=repo_link(repo),
        fields=[("Forks", str(total))],
        url=f"https://github.com/{repo}",
        group=f"{kind}:{repo}",
    )


def format_watch(login: str, repo: str) -> Alert:
    return alert_card(
        "watch",
        "👁",
        "Repository watched",
        body=f"{user_link(login)} is now watching {repo_link(repo)}.",
        url=f"https://github.com/{repo}",
        actor=login,
        group=f"watch:{repo}",
    )


def format_unwatch(login: str, repo: str) -> Alert:
    return alert_card(
        "unwatch",
        "👁",
        "Watch removed",
        body=f"{user_link(login)} stopped watching {repo_link(repo)}.",
        url=f"https://github.com/{repo}",
        actor=login,
        group=f"unwatch:{repo}",
    )


def format_traffic(repo: str, metric: str, date: str, count: int, uniques: int) -> Alert:
    if metric == "views":
        icon, label = "👁", "Repository views"
    else:
        icon, label = "📥", "Repository clones"
    return alert_card(
        f"traffic_{metric}",
        icon,
        label,
        body=repo_link(repo),
        fields=[
            ("Unique visitors", str(uniques)),
            ("Total", str(count)),
            ("Date", escape(date[:10])),
        ],
        url=f"https://github.com/{repo}/graphs/traffic",
    )


def format_welcome(
    username: str,
    followers: int,
    repos: int,
    stars: int,
    bot_username: str | None = None,
) -> Alert:
    bot = f"@{bot_username}" if bot_username else "GitSnapBot"
    rich = (
        f"<h1>{escape(bot)}</h1>"
        f"<p>This chat is connected to {user_link(username)}. GitHub activity "
        f"is collected throughout the week and delivered as a single report.</p>"
        f"<table bordered striped compact>"
        f"<tr><th>Followers</th><td>{followers}</td></tr>"
        f"<tr><th>Repositories</th><td>{repos}</td></tr>"
        f"<tr><th>Stars</th><td>{stars}</td></tr>"
        f"</table>"
        f"<ul>"
        f"<li>Use <b>Report</b> to preview the current digest</li>"
        f"<li>Use <b>Status</b> to view queue size and the next delivery time</li>"
        f"</ul>"
        f"<details><summary>Reporting limits</summary>"
        f"<p>GitHub does not expose profile page views. Repository traffic "
        f"(views and clones) is reported instead.</p></details>"
    )
    fallback = (
        f"<b>{escape(bot)}</b>\n\n"
        f"Connected to {user_link(username)}\n"
        f"Followers  ·  {followers}\n"
        f"Repositories  ·  {repos}\n"
        f"Stars  ·  {stars}\n\n"
        f"GitHub activity is collected throughout the week and delivered as a single report.\n"
        f"Use Report to preview the current digest.\n\n"
        f"<i>GitHub does not expose profile page views. Repository traffic is reported instead.</i>"
    )
    return Alert(kind="welcome", text=rich, fallback=fallback, url=f"https://github.com/{username}")


def format_status(
    username: str,
    followers: int,
    repos: int,
    sent: int,
    paused: bool,
    rate_remaining: int | None,
    rate_limit: int | None,
    last_poll: str | None,
    queued: int = 0,
    next_digest: str | None = None,
) -> Alert:
    rate = "Unknown"
    if rate_remaining is not None and rate_limit is not None:
        rate = f"{rate_remaining}/{rate_limit}"
    state = "Paused" if paused else "Running"
    return alert_card(
        "status",
        "📊",
        "Status",
        body=f"Monitoring {user_link(username)}",
        fields=[
            ("State", state),
            ("Followers", str(followers)),
            ("Repositories", str(repos)),
            ("Queued for report", str(queued)),
            ("Next report", escape(next_digest or "Not scheduled")),
            ("Reports sent", str(sent)),
            ("API quota remaining", escape(rate)),
            ("Last poll", escape(last_poll or "None")),
        ],
        url=f"https://github.com/{username}",
    )


def format_notification(notification: dict[str, Any]) -> Alert | None:
    reason = notification.get("reason") or ""
    label = NOTIFICATION_REASONS.get(reason, reason.replace("_", " ") or "You were notified.")
    if label is None:
        return None
    subject = notification.get("subject") or {}
    repo = (notification.get("repository") or {}).get("full_name") or "unknown/unknown"
    title = subject.get("title") or "Notification"
    ntype = subject.get("type") or "Thread"
    url = html_url_from_api(subject.get("url"))
    return alert_card(
        "notification",
        "🔔",
        ntype,
        body=escape(label),
        quote=escape(title),
        fields=[("Repository", repo_link(repo))],
        url=url or f"https://github.com/{repo}",
    )


def format_event(event: dict[str, Any]) -> Alert | None:
    event_type = event.get("type") or "Event"
    handler = EVENT_FORMATTERS.get(event_type, _format_generic)
    return handler(event)


def _base(event: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
    return actor_login(event), repo_name(event), parse_time(event.get("created_at")), event.get("payload") or {}


def _format_watch(event: dict[str, Any]) -> Alert:
    actor, repo, _, _ = _base(event)
    alert = format_star(actor, repo)
    alert.url = event_url(event)
    return alert


def _format_fork(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    forkee = (payload.get("forkee") or {}).get("full_name") or f"{actor}/{repo.split('/', 1)[-1]}"
    return alert_card(
        "fork",
        "🍴",
        "New fork",
        body=f"{user_link(actor)} forked {repo_link(repo)}.",
        fields=[("Destination", repo_link(forkee))],
        url=(payload.get("forkee") or {}).get("html_url") or event_url(event),
        actor=actor,
    )


def _format_issues(event: dict[str, Any]) -> Alert | None:
    actor, repo, _, payload = _base(event)
    action = payload.get("action") or "updated"
    if action in NOISY_ISSUE_ACTIONS:
        return None
    issue = payload.get("issue") or {}
    number = issue.get("number") or "?"
    title = issue.get("title") or ""
    url = issue.get("html_url") or event_url(event)
    return alert_card(
        "issue",
        "🐛",
        f"Issue {action}",
        body=f"{user_link(actor)} {escape(action)} {repo_link(repo)}#{number}.",
        quote=escape(title),
        url=url,
        actor=actor,
    )


def _format_issue_comment(event: dict[str, Any]) -> Alert | None:
    actor, repo, _, payload = _base(event)
    action = payload.get("action") or "created"
    if action != "created":
        return None
    issue = payload.get("issue") or {}
    comment = payload.get("comment") or {}
    number = issue.get("number") or "?"
    kind = "pr_comment" if issue.get("pull_request") else "comment"
    return alert_card(
        kind,
        "💬",
        "Comment",
        body=f"{user_link(actor)} commented on {repo_link(repo)}#{number}.",
        quote=short_body(comment.get("body")),
        url=comment.get("html_url") or issue.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_pull_request(event: dict[str, Any]) -> Alert | None:
    actor, repo, _, payload = _base(event)
    action = payload.get("action") or "updated"
    if action in NOISY_PR_ACTIONS:
        return None
    pr = payload.get("pull_request") or {}
    number = payload.get("number") or pr.get("number") or "?"
    title = pr.get("title") or ""
    if action == "closed" and pr.get("merged"):
        action = "merged"
    return alert_card(
        "pr",
        "🔀",
        f"Pull request {action}",
        body=f"{user_link(actor)} {escape(action)} {repo_link(repo)}#{number}.",
        quote=escape(title),
        url=pr.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_review(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    review = payload.get("review") or {}
    pr = payload.get("pull_request") or {}
    state = (review.get("state") or "commented").replace("_", " ")
    number = pr.get("number") or "?"
    return alert_card(
        "review",
        "🔎",
        f"Review {state}",
        body=f"{user_link(actor)} reviewed {repo_link(repo)}#{number}.",
        quote=short_body(review.get("body")) or None,
        url=review.get("html_url") or pr.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_review_comment(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    comment = payload.get("comment") or {}
    pr = payload.get("pull_request") or {}
    number = pr.get("number") or "?"
    return alert_card(
        "review_comment",
        "💬",
        "Review comment",
        body=f"{user_link(actor)} commented on {repo_link(repo)}#{number}.",
        quote=short_body(comment.get("body")),
        url=comment.get("html_url") or pr.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_push(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    ref = payload.get("ref") or ""
    branch = ref.replace("refs/heads/", "") if ref.startswith("refs/heads/") else ref
    size = payload.get("size") or len(payload.get("commits") or [])
    fields = [("Commits", str(size))]
    if branch:
        fields.append(("Branch", f"<code>{escape(branch)}</code>"))
    return alert_card(
        "push",
        "📦",
        "Push",
        body=f"{user_link(actor)} pushed to {repo_link(repo)}.",
        fields=fields,
        url=f"https://github.com/{repo}/commits/{branch}" if branch else event_url(event),
        actor=actor,
    )


def _format_create(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    ref_type = payload.get("ref_type") or "repository"
    ref = payload.get("ref")
    fields = [("Type", escape(ref_type))]
    if ref:
        fields.append(("Name", f"<code>{escape(ref)}</code>"))
    return alert_card(
        "create",
        "＋",
        f"Created {ref_type}",
        body=f"{user_link(actor)} created a {escape(ref_type)} on {repo_link(repo)}.",
        fields=fields,
        url=event_url(event),
        actor=actor,
    )


def _format_delete(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    ref_type = payload.get("ref_type") or "ref"
    ref = payload.get("ref") or ""
    return alert_card(
        "delete",
        "－",
        f"Deleted {ref_type}",
        body=f"{user_link(actor)} deleted a {escape(ref_type)} on {repo_link(repo)}.",
        fields=[("Name", f"<code>{escape(ref)}</code>")],
        url=event_url(event),
        actor=actor,
    )


def _format_release(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    release = payload.get("release") or {}
    name = release.get("name") or release.get("tag_name") or "release"
    action = payload.get("action") or "published"
    return alert_card(
        "release",
        "🏷",
        f"Release {action}",
        body=f"{user_link(actor)} {escape(action)} a release on {repo_link(repo)}.",
        quote=escape(name),
        url=release.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_member(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    member = (payload.get("member") or {}).get("login") or "someone"
    action = payload.get("action") or "added"
    return alert_card(
        "member",
        "👤",
        f"Collaborator {action}",
        body=f"{user_link(member)} was {escape(action)} to {repo_link(repo)}.",
        fields=[("By", user_link(actor))] if actor != member else None,
        url=event_url(event),
        actor=member,
    )


def _format_public(event: dict[str, Any]) -> Alert:
    actor, repo, _, _ = _base(event)
    return alert_card(
        "public",
        "🌐",
        "Repository made public",
        body=f"{user_link(actor)} made {repo_link(repo)} public.",
        url=event_url(event),
        actor=actor,
    )


def _format_commit_comment(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    comment = payload.get("comment") or {}
    return alert_card(
        "commit_comment",
        "💬",
        "Commit comment",
        body=f"{user_link(actor)} commented on a commit in {repo_link(repo)}.",
        quote=short_body(comment.get("body")),
        url=comment.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_wiki(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    pages = payload.get("pages") or []
    names = ", ".join(escape(page.get("title") or page.get("page_name") or "page") for page in pages[:5])
    return alert_card(
        "wiki",
        "📝",
        "Wiki updated",
        body=f"{user_link(actor)} edited the wiki on {repo_link(repo)}.",
        quote=names or None,
        url=event_url(event),
        actor=actor,
    )


def _format_sponsor(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    action = payload.get("action") or "created"
    return alert_card(
        "sponsor",
        "♥",
        f"Sponsorship {action}",
        body=f"{user_link(actor)} {escape(action)} a sponsorship.",
        url=f"https://github.com/sponsors/{repo.split('/', 1)[0]}",
        actor=actor,
    )


def _format_discussion(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    discussion = payload.get("discussion") or {}
    action = payload.get("action") or "updated"
    return alert_card(
        "discussion",
        "💬",
        f"Discussion {action}",
        body=f"{user_link(actor)} {escape(action)} a discussion on {repo_link(repo)}.",
        quote=escape(discussion.get("title") or ""),
        url=discussion.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_discussion_comment(event: dict[str, Any]) -> Alert:
    actor, repo, _, payload = _base(event)
    comment = payload.get("comment") or {}
    discussion = payload.get("discussion") or {}
    return alert_card(
        "discussion_comment",
        "💬",
        "Discussion comment",
        body=f"{user_link(actor)} commented on a discussion in {repo_link(repo)}.",
        quote=short_body(comment.get("body")),
        url=comment.get("html_url") or discussion.get("html_url") or event_url(event),
        actor=actor,
    )


def _format_generic(event: dict[str, Any]) -> Alert:
    actor, repo, when, _ = _base(event)
    event_type = event.get("type") or "Event"
    label = event_type.replace("Event", "")
    fields = [("When", escape(when))] if when else None
    return alert_card(
        GENERIC_KIND.get(event_type, "activity"),
        "•",
        label,
        body=f"{user_link(actor)} on {repo_link(repo)}.",
        fields=fields,
        url=event_url(event),
        actor=actor,
    )


EVENT_FORMATTERS = {
    "WatchEvent": _format_watch,
    "ForkEvent": _format_fork,
    "IssuesEvent": _format_issues,
    "IssueCommentEvent": _format_issue_comment,
    "PullRequestEvent": _format_pull_request,
    "PullRequestReviewEvent": _format_review,
    "PullRequestReviewCommentEvent": _format_review_comment,
    "PushEvent": _format_push,
    "CreateEvent": _format_create,
    "DeleteEvent": _format_delete,
    "ReleaseEvent": _format_release,
    "MemberEvent": _format_member,
    "PublicEvent": _format_public,
    "CommitCommentEvent": _format_commit_comment,
    "GollumEvent": _format_wiki,
    "SponsorshipEvent": _format_sponsor,
    "DiscussionEvent": _format_discussion,
    "DiscussionCommentEvent": _format_discussion_comment,
}


def compact_alerts(alerts: list[Alert], threshold: int = 4) -> list[Alert]:
    """Collapse many same-kind events from one poll into a digest."""
    if len(alerts) <= 1:
        return alerts

    grouped: dict[str, list[Alert]] = {}
    order: list[str] = []
    for alert in alerts:
        key = alert.group or f"solo:{id(alert)}"
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(alert)

    compacted: list[Alert] = []
    for key in order:
        bucket = grouped[key]
        if len(bucket) < threshold or key.startswith("solo:"):
            compacted.extend(bucket)
            continue
        actors = [item.actor for item in bucket if item.actor]
        unique_actors = list(dict.fromkeys(actors))
        shown = ", ".join(user_link(login) for login in unique_actors[:8])
        extra = (
            f", and {len(unique_actors) - 8} additional accounts"
            if len(unique_actors) > 8
            else ""
        )
        kind = bucket[0].kind
        titles = {
            "follow": ("➕", "New followers"),
            "unfollow": ("➖", "Followers removed"),
            "deleted": ("⚠️", "Accounts deleted"),
            "star": ("⭐", "Starred"),
            "unstar": ("⭐", "Stars removed"),
            "fork": ("🍴", "Forked"),
            "unfork": ("🍴", "Forks removed"),
            "watch": ("👁", "New watchers"),
            "unwatch": ("👁", "Watchers removed"),
        }
        icon, title = titles.get(kind, ("•", f"{kind.replace('_', ' ').title()}"))
        compacted.append(
            alert_card(
                kind,
                icon,
                f"{title} ({len(bucket)})",
                body=f"{shown}{extra}",
                url=bucket[0].url,
                actor=unique_actors[0] if unique_actors else None,
            )
        )
    return compacted
