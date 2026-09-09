from gitsnapbot.config import Config
from gitsnapbot.github_api import GitHubClient


def test_if_none_match_header_is_sent() -> None:
    cfg = Config(github_token="tok", telegram_bot_token="bot")
    client = GitHubClient.__new__(GitHubClient)
    client.config = cfg
    client.token = cfg.github_token
    headers = GitHubClient._headers(client, etag='"abc"')
    assert headers["If-None-Match"] == '"abc"'
    assert headers["User-Agent"] == cfg.user_agent
    assert "If-None-Match" not in GitHubClient._headers(client)
