from gitsnapbot.github_api import next_link
from gitsnapbot.messages import (
    compact_alerts,
    signed,
    escape,
    format_event,
    format_follow,
    format_notification,
    format_star,
    format_unstar,
    html_url_from_api,
    is_relevant_event,
    short_body,
)


def test_escape_html() -> None:
    assert escape("<script> &") == "&lt;script&gt; &amp;"


def test_short_body_collapses_and_truncates() -> None:
    text = short_body("hello\n\nworld " * 40, limit=40)
    assert "\n" not in text
    assert text.endswith("…")
    assert len(text) <= 40


def test_html_url_from_api() -> None:
    assert (
        html_url_from_api("https://api.github.com/repos/octo/hello/issues/12")
        == "https://github.com/octo/hello/issues/12"
    )
    assert (
        html_url_from_api("https://api.github.com/repos/octo/hello/pulls/3")
        == "https://github.com/octo/hello/pull/3"
    )


def test_follow_and_star_messages_include_links() -> None:
    follow = format_follow("octocat", 12)
    assert "octocat" in follow.text
    assert "<h2>" in follow.text
    assert follow.fallback and "octocat" in follow.fallback
    assert follow.url == "https://github.com/octocat"
    star = format_star("octocat", "me/repo", 4)
    assert "me/repo" in star.text
    unstar = format_unstar("octocat", "me/repo", 3)
    assert "Star removed" in unstar.text


def test_watch_event() -> None:
    alert = format_event(
        {
            "type": "WatchEvent",
            "actor": {"login": "octocat"},
            "repo": {"name": "me/repo"},
            "payload": {"action": "started"},
            "created_at": "2026-01-01T00:00:00Z",
        }
    )
    assert alert is not None
    assert alert.kind == "star"
    assert "octocat" in alert.text


def test_issue_opened() -> None:
    alert = format_event(
        {
            "type": "IssuesEvent",
            "actor": {"login": "octocat"},
            "repo": {"name": "me/repo"},
            "payload": {
                "action": "opened",
                "issue": {
                    "number": 7,
                    "title": "Bug <here>",
                    "html_url": "https://github.com/me/repo/issues/7",
                },
            },
        }
    )
    assert alert is not None
    assert alert.kind == "issue"
    assert "Bug &lt;here&gt;" in alert.text
    assert alert.url.endswith("/issues/7")


def test_skips_noisy_issue_edits() -> None:
    alert = format_event(
        {
            "type": "IssuesEvent",
            "actor": {"login": "octocat"},
            "repo": {"name": "me/repo"},
            "payload": {"action": "edited", "issue": {"number": 1, "title": "x"}},
        }
    )
    assert alert is None


def test_pr_merged() -> None:
    alert = format_event(
        {
            "type": "PullRequestEvent",
            "actor": {"login": "octocat"},
            "repo": {"name": "me/repo"},
            "payload": {
                "action": "closed",
                "number": 9,
                "pull_request": {
                    "number": 9,
                    "title": "Add feature",
                    "merged": True,
                    "html_url": "https://github.com/me/repo/pull/9",
                },
            },
        }
    )
    assert alert is not None
    assert "merged" in alert.text


def test_relevant_event_filters_other_owners() -> None:
    event = {
        "type": "WatchEvent",
        "repo": {"name": "someone-else/repo"},
        "actor": {"login": "octocat"},
    }
    assert is_relevant_event(event, {"me"}) is False
    event["repo"]["name"] = "me/repo"
    assert is_relevant_event(event, {"me"}) is True


def test_notification_mention() -> None:
    alert = format_notification(
        {
            "reason": "mention",
            "subject": {
                "title": "Please look",
                "type": "Issue",
                "url": "https://api.github.com/repos/foo/bar/issues/1",
            },
            "repository": {"full_name": "foo/bar"},
        }
    )
    assert alert is not None
    assert "You were mentioned." in (alert.fallback or alert.text)
    assert alert.url == "https://github.com/foo/bar/issues/1"


def test_skips_subscribed_notifications() -> None:
    assert format_notification({"reason": "subscribed", "subject": {}, "repository": {}}) is None


def test_compact_alerts_groups_follows() -> None:
    alerts = [format_follow(f"user{i}", 10 + i) for i in range(5)]
    compacted = compact_alerts(alerts, threshold=4)
    assert len(compacted) == 1
    assert "New followers" in compacted[0].text
    assert "(5)" in compacted[0].text


def test_signature_appends_gitsnapbot_mark() -> None:
    alert = format_follow("octocat", 3)
    signed_alert = signed(alert, "GitSnapBot")
    assert "<footer>GitSnapBot</footer>" in signed_alert.text
    assert signed_alert.fallback and signed_alert.fallback.endswith("<i>GitSnapBot</i>")


def test_next_link_parser() -> None:
    header = (
        '<https://api.github.com/resource?page=2>; rel="next", '
        '<https://api.github.com/resource?page=5>; rel="last"'
    )
    assert next_link(header) == "https://api.github.com/resource?page=2"
    assert next_link(None) is None
