from gitsnapbot.config import Config


def test_from_env_reads_signature_and_budgets(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("BOT_SIGNATURE", "GitSnapBot")
    monkeypatch.setenv("USER_AGENT", "GitSnapBot/1.0")
    monkeypatch.setenv("MAX_ACTORS_PER_REPO", "1500")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "60")
    cfg = Config.from_env()
    assert cfg.bot_signature == "GitSnapBot"
    assert cfg.user_agent == "GitSnapBot/1.0"
    assert cfg.max_actors_per_repo == 1500
    assert cfg.poll_interval_seconds == 60
    assert cfg.github_api_url == "https://api.github.com"
