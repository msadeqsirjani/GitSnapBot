from __future__ import annotations

from gitsnapbot.github_api import GitHubError
from gitsnapbot.messages import Alert

TOKEN_NOTICE = (
    "GitHub rejected the access token (unauthorized). "
    "Create a new personal access token, set GITHUB_TOKEN in .env, and restart GitSnapBot."
)


def is_unauthorized(exc: BaseException) -> bool:
    return isinstance(exc, GitHubError) and exc.status == 401


def token_alert() -> Alert:
    return Alert(kind="system", text=TOKEN_NOTICE, fallback=TOKEN_NOTICE)
