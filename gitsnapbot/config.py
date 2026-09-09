from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo


def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise SystemExit(f"{name} must be >= {minimum}")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise SystemExit(f"{name} must be >= {minimum}")
    return value


@dataclass(slots=True)
class Config:
    github_token: str
    telegram_bot_token: str
    github_username: str | None = None
    telegram_chat_id: str | None = None
    poll_interval_seconds: int = 21600
    follower_reconcile_seconds: int = 0
    star_reconcile_seconds: int = 0
    watcher_reconcile_seconds: int = 0
    traffic_interval_seconds: int = 0
    include_owned_forks: bool = False
    include_events: bool = True
    include_notifications: bool = False
    include_watchers: bool = False
    include_traffic: bool = False
    include_deleted_check: bool = False
    include_repo_event_fallback: bool = True
    github_orgs: list[str] = field(default_factory=list)
    log_level: str = "INFO"
    data_dir: Path = Path("./data")
    bot_signature: str = "GitSnapBot"
    user_agent: str = "GitSnapBot/1.0"
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2022-11-28"
    telegram_api_url: str = "https://api.telegram.org"
    github_per_page: int = 100
    github_max_pages: int = 50
    github_actor_max_pages: int = 20
    github_received_event_pages: int = 1
    github_repo_event_pages: int = 1
    max_actors_per_repo: int = 2000
    max_actor_lookups_per_poll: int = 4
    max_actor_backfills_per_poll: int = 8
    max_departure_lookups_per_poll: int = 8
    alert_compact_threshold: int = 4
    events_keep: int = 1500
    http_timeout_seconds: float = 40.0
    http_connect_timeout_seconds: float = 15.0
    telegram_long_poll_seconds: int = 25
    telegram_message_limit: int = 4000
    error_notice_seconds: int = 1800
    digest_period: str = "weekly"
    digest_weekday: int = 0
    digest_hour: int = 9
    digest_minute: int = 0
    digest_timezone: str = "America/Chicago"
    digest_max_lines: int = 20
    digest_send_empty: bool = True
    digest_top_repos: int = 5
    digest_pin: bool = True
    bot_short_description: str = "Weekly GitHub activity report for your profile."
    bot_description: str = (
        "GitSnapBot watches your GitHub account and sends one weekly report: "
        "follows, stars, forks, issues, pull requests, and more. "
        "Tap Report to preview the queue anytime."
    )
    log_color: bool = True
    log_file: str | None = None
    log_http: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "gitsnapbot.db"

    @classmethod
    def from_env(cls) -> Config:
        data_dir = Path(_env("DATA_DIR", "./data") or "./data")
        chat_id = _env("TELEGRAM_CHAT_ID")
        username = _env("GITHUB_USERNAME")
        signature = _env("BOT_SIGNATURE", "GitSnapBot") or "GitSnapBot"
        user_agent = _env("USER_AGENT", "GitSnapBot/1.0") or "GitSnapBot/1.0"
        github_api = (_env("GITHUB_API_URL", "https://api.github.com") or "https://api.github.com").rstrip("/")
        telegram_api = (_env("TELEGRAM_API_URL", "https://api.telegram.org") or "https://api.telegram.org").rstrip("/")
        from gitsnapbot.digest import parse_weekday

        period = (_env("DIGEST_PERIOD", "weekly") or "weekly").strip().lower()
        if period not in {"weekly", "daily"}:
            raise SystemExit("DIGEST_PERIOD must be weekly or daily")
        weekday = parse_weekday(_env("DIGEST_WEEKDAY", "monday") or "monday")
        tz_name = _env("DIGEST_TIMEZONE", "America/Chicago") or "America/Chicago"
        try:
            ZoneInfo(tz_name)
        except Exception as exc:
            raise SystemExit(f"Unknown DIGEST_TIMEZONE {tz_name!r}") from exc
        digest_hour = _env_int("DIGEST_HOUR", 9, minimum=0)
        digest_minute = _env_int("DIGEST_MINUTE", 0, minimum=0)
        if digest_hour > 23 or digest_minute > 59:
            raise SystemExit("DIGEST_HOUR must be 0-23 and DIGEST_MINUTE must be 0-59")
        return cls(
            github_token=_env("GITHUB_TOKEN", required=True) or "",
            telegram_bot_token=_env("TELEGRAM_BOT_TOKEN", required=True) or "",
            github_username=username.lower() if username else None,
            telegram_chat_id=chat_id,
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 21600),
            follower_reconcile_seconds=_env_int("FOLLOWER_RECONCILE_SECONDS", 0, minimum=0),
            star_reconcile_seconds=_env_int("STAR_RECONCILE_SECONDS", 0, minimum=0),
            watcher_reconcile_seconds=_env_int("WATCHER_RECONCILE_SECONDS", 0, minimum=0),
            traffic_interval_seconds=_env_int("TRAFFIC_INTERVAL_SECONDS", 0, minimum=0),
            include_owned_forks=_env_bool("INCLUDE_OWNED_FORKS", False),
            include_events=_env_bool("INCLUDE_EVENTS", True),
            include_notifications=_env_bool("INCLUDE_NOTIFICATIONS", False),
            include_watchers=_env_bool("INCLUDE_WATCHERS", False),
            include_traffic=_env_bool("INCLUDE_TRAFFIC", False),
            include_deleted_check=_env_bool("INCLUDE_DELETED_CHECK", False),
            include_repo_event_fallback=_env_bool("INCLUDE_REPO_EVENT_FALLBACK", True),
            github_orgs=[item.lower() for item in _env_list("GITHUB_ORGS")],
            log_level=(_env("LOG_LEVEL", "INFO") or "INFO").upper(),
            data_dir=data_dir,
            bot_signature=signature,
            user_agent=user_agent,
            github_api_url=github_api,
            github_api_version=_env("GITHUB_API_VERSION", "2022-11-28") or "2022-11-28",
            telegram_api_url=telegram_api,
            github_per_page=_env_int("GITHUB_PER_PAGE", 100),
            github_max_pages=_env_int("GITHUB_MAX_PAGES", 50),
            github_actor_max_pages=_env_int("GITHUB_ACTOR_MAX_PAGES", 20),
            github_received_event_pages=_env_int("GITHUB_RECEIVED_EVENT_PAGES", 1),
            github_repo_event_pages=_env_int("GITHUB_REPO_EVENT_PAGES", 1),
            max_actors_per_repo=_env_int("MAX_ACTORS_PER_REPO", 2000),
            max_actor_lookups_per_poll=_env_int("MAX_ACTOR_LOOKUPS_PER_POLL", 4),
            max_actor_backfills_per_poll=_env_int("MAX_ACTOR_BACKFILLS_PER_POLL", 8),
            max_departure_lookups_per_poll=_env_int("MAX_DEPARTURE_LOOKUPS_PER_POLL", 8),
            alert_compact_threshold=_env_int("ALERT_COMPACT_THRESHOLD", 4),
            events_keep=_env_int("EVENTS_KEEP", 1500),
            http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 40.0, minimum=1.0),
            http_connect_timeout_seconds=_env_float("HTTP_CONNECT_TIMEOUT_SECONDS", 15.0, minimum=1.0),
            telegram_long_poll_seconds=_env_int("TELEGRAM_LONG_POLL_SECONDS", 25),
            telegram_message_limit=_env_int("TELEGRAM_MESSAGE_LIMIT", 4000),
            error_notice_seconds=_env_int("ERROR_NOTICE_SECONDS", 1800),
            digest_period=period,
            digest_weekday=weekday,
            digest_hour=digest_hour,
            digest_minute=digest_minute,
            digest_timezone=tz_name,
            digest_max_lines=_env_int("DIGEST_MAX_LINES", 20),
            digest_send_empty=_env_bool("DIGEST_SEND_EMPTY", True),
            digest_top_repos=_env_int("DIGEST_TOP_REPOS", 5),
            digest_pin=_env_bool("DIGEST_PIN", True),
            bot_short_description=_env(
                "BOT_SHORT_DESCRIPTION",
                "Weekly GitHub activity report for your profile.",
            )
            or "Weekly GitHub activity report for your profile.",
            bot_description=_env(
                "BOT_DESCRIPTION",
                "GitSnapBot watches your GitHub account and sends one weekly report: "
                "follows, stars, forks, issues, pull requests, and more. "
                "Tap Report to preview the queue anytime.",
            )
            or "GitSnapBot watches your GitHub account and sends one weekly report.",
            log_color=_env_bool("LOG_COLOR", True),
            log_file=(os.getenv("LOG_FILE", "./data/gitsnapbot.log") or None),
            log_http=_env_bool("LOG_HTTP", True),
        )
