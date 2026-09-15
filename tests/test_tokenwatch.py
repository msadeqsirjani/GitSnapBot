from gitsnapbot.features.tokenwatch import TOKEN_NOTICE, is_unauthorized, token_alert
from gitsnapbot.github_api import Forbidden, GitHubError


def test_is_unauthorized_only_for_401() -> None:
    assert is_unauthorized(GitHubError("bad token", status=401)) is True
    assert is_unauthorized(GitHubError("oops", status=500)) is False
    assert is_unauthorized(Forbidden("nope", status=403)) is False
    assert is_unauthorized(RuntimeError("no")) is False


def test_token_alert_is_system_notice() -> None:
    alert = token_alert()
    assert alert.kind == "system"
    assert "GITHUB_TOKEN" in alert.text
    assert TOKEN_NOTICE in (alert.fallback or "")
