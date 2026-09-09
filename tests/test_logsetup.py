from gitsnapbot.logsetup import short_url, startup_banner


def test_short_url_redacts_telegram_token() -> None:
    raw = "https://api.telegram.org/bot123456:secret/sendMessage"
    assert short_url(raw) == "/bot***/sendMessage"
    assert "secret" not in short_url(raw)


def test_short_url_strips_github_host() -> None:
    assert short_url("https://api.github.com/user") == "/user"


def test_startup_banner_contains_identity() -> None:
    text = startup_banner(
        github_login="octocat",
        telegram_username="gitsnapbot",
        poll_seconds=21600,
        digest_label="Mon 14 Sep 2026 09:00 UTC",
        remaining=4990,
        limit=5000,
        queued=3,
        paused=False,
    )
    assert "GitSnapBot" in text
    assert "@octocat" in text
    assert "@gitsnapbot" in text
    assert "every 6h" in text
    assert "3 items" in text
