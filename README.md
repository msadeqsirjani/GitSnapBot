# GitSnapBot

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-pytest-informational)](tests/)

Self-hosted Telegram bot that watches **your** GitHub account and delivers **one weekly digest** instead of a message per event.

GitHub does not notify you of follows, unfollows, stars, or unstars. GitSnapBot polls the API, diffs snapshots, queues changes, and sends a single report at a time you choose.

---

## Features

- **Weekly digest** — grouped sections, week-over-week follower/star totals, top starred repos, quiet-week card
- **Social graph** — follow, unfollow, deleted accounts, star, unstar, fork, unfork
- **Repository activity** — issues, pull requests, comments, reviews, releases, and related events
- **Token-aware polling** — ETag / `304 Not Modified` (does not spend quota), list stargazers only when counts move
- **Telegram UX** — command menu, persistent keyboard, Rich Messages with HTML fallback
- **Durable queue** — SQLite; a failed Telegram send does not drop the week’s events
- **Ops-friendly** — structured logs, Docker, macOS LaunchAgent

## How it works

```
GitHub REST API  ──poll──►  SQLite snapshot + digest queue  ──schedule──►  Telegram
```

1. On first run, GitSnapBot stores a **baseline** (existing followers and stars are not reported).
2. Later polls compare lists and counts, then enqueue new activity.
3. At `DIGEST_WEEKDAY` + `DIGEST_HOUR` in `DIGEST_TIMEZONE`, one report is sent (and pinned, if enabled).
4. `/digest` or **📬 Report** sends the current queue immediately.

Stars and forks are taken from **repository counts**, not the public received-events feed. That feed is capped and turns over quickly; a count diff is exact and has no retention window.

## What is reported

| Event | Source |
| --- | --- |
| Follow / unfollow | Follower list diff |
| Account deleted vs unfollow | `GET /users/{login}` → `404` |
| Star / unstar | `stargazers_count` + stargazer list (admin/collaborator token) |
| Fork / unfork | `forks_count` + forks list |
| Named star/fork when the list is blocked | Public repo `WatchEvent` / `ForkEvent` |
| Issues, PRs, comments, reviews, releases | Events on repositories you own |
| Mentions, review requests, security alerts | Notifications API (off by default) |
| Repo views / clones | Traffic API (off by default; not profile views) |

### Limitations

- GitHub **does not expose profile page views**. README visitor badges are not used.
- Only **net change between polls** is visible. A follow and unfollow in the same window cancel out.
- Repositories with more than `MAX_ACTORS_PER_REPO` (default 2000) stars or forks are tracked by count only.
- Unstar **names** require permission to list stargazers (repo admin or collaborator).

## Requirements

- Python **3.11+**
- A [Telegram bot token](https://t.me/BotFather)
- A GitHub [personal access token](https://github.com/settings/tokens) (classic `public_repo` or `repo` is the practical minimum; add `notifications` if you enable that feed)

## Quick start

```bash
cd GitSnapBot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Set at least:

```env
GITHUB_TOKEN=ghp_...
TELEGRAM_BOT_TOKEN=123456:ABC...
DIGEST_TIMEZONE=America/Chicago
```

Run:

```bash
python -m gitsnapbot
```

Open the bot in Telegram and send `/start`. The process must stay running until the next digest slot (default **Monday 09:00** in `DIGEST_TIMEZONE`).

## Commands

| Command | Description |
| --- | --- |
| `/start` | Bind this chat and show the dashboard |
| `/status` | Queue size, next report, API remaining |
| `/digest` | Preview the current queue (does not clear it or change the pin) |
| `/last` | Show the last scheduled report |
| `/when` | Show or change the schedule (`/when monday 9:00`, `/when timezone Asia/Tehran`, `/when brief on`) |
| `/pause` | Stop collecting |
| `/resume` | Resume collecting |
| `/help` | Short usage |

The chat also has a persistent keyboard: **Status**, **Report**, **Last report**, **Pause** / **Resume**, **Help**. Only the bound chat (first `/start`, or `TELEGRAM_CHAT_ID`) is accepted.

## Configuration

All runtime settings are environment variables. Copy [`.env.example`](.env.example) and edit `.env` — nothing important is hardcoded.

| Variable | Default | Meaning |
| --- | --- | --- |
| `GITHUB_TOKEN` | — | **Required.** GitHub PAT |
| `TELEGRAM_BOT_TOKEN` | — | **Required.** BotFather token |
| `TELEGRAM_CHAT_ID` | unset | Optional; otherwise `/start` binds the chat |
| `DIGEST_PERIOD` | `weekly` | `weekly` or `daily` |
| `DIGEST_WEEKDAY` | `monday` | Day of week for weekly reports |
| `DIGEST_HOUR` / `DIGEST_MINUTE` | `9` / `0` | Local time of send |
| `DIGEST_TIMEZONE` | `America/Chicago` | IANA timezone |
| `POLL_INTERVAL_SECONDS` | `21600` | GitHub poll interval (6 hours) |
| `INCLUDE_EVENTS` | `true` | Issues / PRs / comments feed |
| `INCLUDE_NOTIFICATIONS` | `false` | Mentions on other people’s repos |
| `INCLUDE_WATCHERS` | `false` | Repo watchers |
| `INCLUDE_TRAFFIC` | `false` | Views and clones |
| `LOG_FILE` | `./data/gitsnapbot.log` | Rotating file is not used; path is appended |

See `.env.example` for pagination, rate-limit budgets, and Telegram limits.

## Deployment

### Docker

```bash
cp .env.example .env   # fill in tokens
docker compose up -d --build
```

SQLite and logs live in `./data`. The compose service uses `restart: unless-stopped`.

### macOS (LaunchAgent)

Stop any foreground `python -m gitsnapbot`, then:

```bash
./scripts/install-macos.sh
```

The agent starts at login and restarts on crash. Unload with:

```bash
launchctl bootout "gui/$(id -u)/com.gitsnapbot"
```

## Development

```bash
pip install -r requirements-dev.txt
pytest
```

Requires-python is `>=3.11` ([`pyproject.toml`](pyproject.toml)).

## Security

- Never commit `.env`. It is gitignored; only `.env.example` belongs in the repository.
- Treat `GITHUB_TOKEN` as a password. If it leaked, [revoke it](https://github.com/settings/tokens) and issue a new one.
- The bot token appears in Telegram API URLs internally; logs redact it as `/bot***/…`.

## License

[MIT](LICENSE)
