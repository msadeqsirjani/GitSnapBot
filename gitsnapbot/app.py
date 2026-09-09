from __future__ import annotations

import asyncio
import logging
import signal
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from gitsnapbot.config import Config
from gitsnapbot.digest import digest_is_due, format_weekly_digest, next_digest_slot
from gitsnapbot.github_api import GitHubClient, GitHubError
from gitsnapbot.logsetup import print_banner, startup_banner
from gitsnapbot.messages import Alert, format_status, format_welcome
from gitsnapbot.store import Store
from gitsnapbot.telegram_api import TelegramClient, TelegramError
from gitsnapbot.tracker import Tracker
from gitsnapbot.ui import (
    BOT_COMMANDS,
    BUTTON_TO_COMMAND,
    HELP_FALLBACK,
    HELP_RICH,
    activity_inline,
    main_keyboard,
    status_inline,
)

log = logging.getLogger("gitsnapbot")


class BotApp:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.store = Store(config.db_path)
        self.running = True
        self._http: httpx.AsyncClient | None = None
        self.github: GitHubClient | None = None
        self.telegram: TelegramClient | None = None
        self.tracker: Tracker | None = None
        self._update_offset: int | None = None
        self._consecutive_failures = 0
        self._last_error_notice = 0.0
        self._logged_waiting_chat = False
        self._logged_paused = False
        if config.telegram_chat_id:
            self.store.set_chat_id(config.telegram_chat_id)

    def chat_id(self) -> str | None:
        return self.store.chat_id() or self.config.telegram_chat_id

    async def start(self) -> None:
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        timeout = httpx.Timeout(
            self.config.http_timeout_seconds,
            read=self.config.http_timeout_seconds,
            connect=self.config.http_connect_timeout_seconds,
        )
        self._http = httpx.AsyncClient(timeout=timeout)
        self.github = GitHubClient(self._http, self.config)
        self.telegram = TelegramClient(self._http, self.config)
        self.tracker = Tracker(self.config, self.github, self.store)

        self.github.verbose_http = False
        self.telegram.verbose_http = False
        try:
            profile = await self.github.get_authenticated_user()
            user = profile.data or {}
            me = await self.telegram.get_me()
            await self.telegram.set_my_commands(BOT_COMMANDS)
            await self.telegram.set_chat_menu_button()
            await self.telegram.set_my_short_description(self.config.bot_short_description)
            await self.telegram.set_my_description(self.config.bot_description)
        except GitHubError as exc:
            raise SystemExit(f"GitHub token check failed: {exc}") from exc
        except TelegramError as exc:
            raise SystemExit(f"Telegram bot token check failed: {exc}") from exc
        finally:
            self.github.verbose_http = self.config.log_http
            self.telegram.verbose_http = self.config.log_http

        login = user.get("login") or ""
        if profile.etag:
            self.store.set_meta("etag:user", profile.etag)
        if login:
            self.store.set_meta("user_login", login)
            self.store.set_meta("user_followers", str(int(user.get("followers") or 0)))
            self.tracker.username = login
            self.tracker.owners = {login.lower(), *self.config.github_orgs}
            self.tracker.follower_count = int(user.get("followers") or 0)
        log.info("Cached GitHub profile for the first poll  @%s", login or "unknown")

        print_banner(
            startup_banner(
                github_login=user.get("login") or "unknown",
                telegram_username=me.get("username"),
                poll_seconds=self.config.poll_interval_seconds,
                digest_label=self._next_digest_label(),
                remaining=self.github.rate_remaining,
                limit=self.github.rate_limit,
                queued=self.store.digest_count(),
                paused=self.store.paused(),
            )
        )
        if not self.chat_id():
            log.info("No chat bound yet — open the bot in Telegram and send /start")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                pass

        await asyncio.gather(self.poll_loop(), self.command_loop())

    def stop(self) -> None:
        self.running = False
        log.info("Shutdown requested — finishing in-flight work")

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()
        self.store.close()

    def _keyboard(self) -> dict:
        return main_keyboard(self.store.paused())

    async def send(
        self,
        alert: Alert,
        *,
        chat_id: str | int | None = None,
        with_nav: bool = False,
    ) -> Any:
        target = chat_id or self.chat_id()
        if not target or self.telegram is None:
            return None
        if with_nav:
            markup = self._keyboard()
        elif alert.kind == "status":
            markup = status_inline(self.store.paused())
        else:
            markup = activity_inline(alert)
        if self.config.bot_signature and alert.kind not in {
            "welcome",
            "help",
            "status",
            "system",
            "digest",
        }:
            from gitsnapbot.messages import signed

            alert = signed(alert, self.config.bot_signature)
        log.info(
            "Telegram send  kind=%s  chat=%s  chars=%s",
            alert.kind,
            target,
            len(alert.text),
        )
        result = await self.telegram.send_message(
            target,
            alert.text,
            fallback=alert.fallback,
            reply_markup=markup,
        )
        if alert.kind not in {"welcome", "status", "help", "system"}:
            self.store.increment_sent()
        return result

    def _digest_tz(self) -> ZoneInfo:
        return ZoneInfo(self.config.digest_timezone)

    def _digest_kwargs(self) -> dict[str, Any]:
        return {
            "period": self.config.digest_period,
            "weekday": self.config.digest_weekday,
            "hour": self.config.digest_hour,
            "minute": self.config.digest_minute,
            "tz": self._digest_tz(),
        }

    def _next_digest_label(self) -> str:
        nxt = next_digest_slot(datetime.now(self._digest_tz()), **self._digest_kwargs())
        return nxt.strftime("%a %d %b %Y %H:%M %Z")

    def _queue_alerts(self, alerts: list[Alert]) -> None:
        skip = {"welcome", "status", "help", "system", "digest"}
        rows = [
            {
                "kind": alert.kind,
                "actor": alert.actor,
                "repo": alert.repo,
                "url": alert.url,
                "line": alert.line or alert.kind,
            }
            for alert in alerts
            if alert.kind not in skip
        ]
        self.store.queue_digest(rows)
        if rows:
            kinds: dict[str, int] = {}
            for row in rows:
                kind = row.get("kind") or "activity"
                kinds[kind] = kinds.get(kind, 0) + 1
            summary = ", ".join(f"{name}={n}" for name, n in sorted(kinds.items()))
            log.info(
                "Queued %s update%s for the weekly report  %s  queue=%s",
                len(rows),
                "" if len(rows) == 1 else "s",
                summary,
                self.store.digest_count(),
            )
        else:
            log.info("No new activity this cycle  queue=%s", self.store.digest_count())

    async def _flush_digest_if_due(
        self,
        *,
        force: bool = False,
        chat_id: str | int | None = None,
    ) -> None:
        assert self.telegram is not None and self.tracker is not None
        now = datetime.now(self._digest_tz())
        last_raw = self.store.last_digest_at()
        last_sent = datetime.fromtimestamp(last_raw, tz=self._digest_tz()) if last_raw else None
        if not force and not digest_is_due(now, last_sent, **self._digest_kwargs()):
            log.debug("Weekly report not due  next=%s", self._next_digest_label())
            return
        log.info(
            "Preparing weekly report  force=%s  queued=%s  period=%s",
            force,
            self.store.digest_count(),
            self.config.digest_period,
        )
        items = self.store.list_digest_items()
        if not items:
            if force and not self.config.digest_send_empty:
                await self.telegram.send_message(
                    chat_id or self.chat_id() or "",
                    "<h2>📬 Weekly report</h2><p>Nothing new is queued yet. I'll keep collecting.</p>",
                    fallback="📬 Nothing new is queued yet. I'll keep collecting.",
                    reply_markup=self._keyboard(),
                )
                return
            if not force and not self.config.digest_send_empty:
                log.info("Weekly slot reached with an empty queue — skipping send")
                self.store.set_last_digest_at(now.timestamp())
                return
        start = last_sent or (now - timedelta(days=7))
        alert = format_weekly_digest(
            items,
            period_start=start,
            period_end=now,
            follower_count=self.tracker.follower_count,
            star_count=self.tracker.star_total,
            prev_followers=self.store.get_int_meta("last_digest_followers"),
            prev_stars=self.store.get_int_meta("last_digest_stars"),
            signature=self.config.bot_signature,
            max_lines=self.config.digest_max_lines,
            top_repo_limit=self.config.digest_top_repos,
        )
        result = await self.send(alert, chat_id=chat_id, with_nav=True)
        if self.config.digest_pin and isinstance(result, dict) and result.get("message_id"):
            try:
                await self.telegram.pin_chat_message(
                    chat_id or self.chat_id() or "",
                    int(result["message_id"]),
                )
                log.info("Pinned the weekly report")
            except TelegramError:
                log.info("Could not pin the weekly report (the bot may lack permission)")
        self.store.clear_digest_items()
        self.store.set_last_digest_at(now.timestamp())
        self.store.set_meta("last_digest_followers", str(self.tracker.follower_count))
        self.store.set_meta("last_digest_stars", str(self.tracker.star_total))
        log.info(
            "Weekly report delivered  items=%s  next=%s",
            len(items),
            self._next_digest_label(),
        )

    async def poll_loop(self) -> None:
        assert self.tracker is not None
        while self.running:
            if not self.chat_id():
                if not self._logged_waiting_chat:
                    log.info("Waiting for /start in Telegram before the first GitHub poll")
                    self._logged_waiting_chat = True
                await asyncio.sleep(2)
                continue
            if self.store.last_digest_at() is None:
                self.store.set_last_digest_at(time.time())
            if self.store.paused():
                if not self._logged_paused:
                    log.info("Collection is paused — GitHub polling is idle")
                    self._logged_paused = True
                await asyncio.sleep(2)
                continue
            self._logged_paused = False
            started = time.monotonic()
            try:
                alerts, pending = await self.tracker.poll()
                pending.apply(self.store, events_keep=self.config.events_keep)
                if pending.boot:
                    if self.store.last_digest_at() is None:
                        self.store.set_last_digest_at(time.time())
                    for alert in alerts:
                        await self.send(alert, with_nav=True)
                else:
                    self._queue_alerts(alerts)
                    await self._flush_digest_if_due()
                self._consecutive_failures = 0
            except TelegramError:
                log.exception("Telegram send failed; weekly report was not marked sent")
            except Exception:
                self._consecutive_failures += 1
                log.exception("Poll failed (%s consecutive)", self._consecutive_failures)
                await self._maybe_notify_error()
            elapsed = time.monotonic() - started
            sleep_for = max(1.0, self.config.poll_interval_seconds - elapsed)
            log.info(
                "Next poll in %ss  queue=%s  next report=%s",
                int(sleep_for),
                self.store.digest_count(),
                self._next_digest_label(),
            )
            await asyncio.sleep(sleep_for)

    async def _maybe_notify_error(self) -> None:
        if self._consecutive_failures < 3:
            return
        now = time.time()
        if now - self._last_error_notice < self.config.error_notice_seconds:
            return
        self._last_error_notice = now
        try:
            await self.send(
                Alert(
                    kind="system",
                    text="⚠️ GitSnapBot could not reach GitHub. I'll keep retrying.",
                )
            )
        except Exception:
            log.exception("Failed to send error notice")

    async def command_loop(self) -> None:
        assert self.telegram is not None
        while self.running:
            try:
                updates = await self.telegram.get_updates(
                    self._update_offset,
                    timeout=self.config.telegram_long_poll_seconds,
                )
            except Exception:
                log.exception("Telegram getUpdates failed")
                await asyncio.sleep(5)
                continue
            for update in updates:
                self._update_offset = int(update["update_id"]) + 1
                try:
                    await self._handle_update(update)
                except Exception:
                    log.exception("Failed to handle Telegram update")

    async def _handle_update(self, update: dict[str, Any]) -> None:
        assert self.telegram is not None
        callback = update.get("callback_query")
        if callback:
            await self._handle_callback(callback)
            return
        message = update.get("message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if not text or chat_id is None:
            return
        command = BUTTON_TO_COMMAND.get(text, text.split()[0].split("@", 1)[0]).lower()
        log.info("Command %s  chat=%s", command, chat_id)
        if command == "/start":
            self.store.set_chat_id(str(chat_id))
            await self._send_start(chat_id)
            return
        if command == "/help":
            await self.telegram.send_message(
                chat_id,
                HELP_RICH,
                fallback=HELP_FALLBACK,
                reply_markup=self._keyboard(),
            )
            return
        if command == "/pause":
            self.store.set_paused(True)
            self._logged_paused = False
            log.info("Collection paused by user")
            await self.telegram.send_message(
                chat_id,
                "<h2>⏸ Collection paused</h2><p>The weekly report will wait. Tap Resume to collect again.</p>",
                fallback="⏸ Collection paused. Tap Resume to collect again.",
                reply_markup=self._keyboard(),
            )
            return
        if command == "/resume":
            self.store.set_paused(False)
            self._logged_paused = False
            log.info("Collection resumed by user")
            await self.telegram.send_message(
                chat_id,
                "<h2>▶️ Collecting again</h2><p>GitHub activity is queued for the next weekly report.</p>",
                fallback="▶️ Collecting again. GitHub activity is queued for the next weekly report.",
                reply_markup=self._keyboard(),
            )
            return
        if command == "/status":
            await self._send_status(chat_id)
            return
        if command == "/digest":
            await self._flush_digest_if_due(force=True, chat_id=chat_id)
            return
        await self.telegram.send_message(
            chat_id,
            "<p>Use the buttons below, or tap <b>Menu</b> next to the input field.</p>",
            fallback="Use the buttons below, or tap Menu next to the input field.",
            reply_markup=self._keyboard(),
        )

    async def _handle_callback(self, callback: dict[str, Any]) -> None:
        assert self.telegram is not None
        data = (callback.get("data") or "").lower()
        chat = ((callback.get("message") or {}).get("chat") or {})
        chat_id = chat.get("id")
        callback_id = callback.get("id")
        if callback_id:
            await self.telegram.answer_callback(callback_id)
        if chat_id is None:
            return
        self.store.set_chat_id(str(chat_id))
        if data == "pause":
            self.store.set_paused(True)
            await self._send_status(chat_id)
            return
        if data == "resume":
            self.store.set_paused(False)
            await self._send_status(chat_id)
            return
        if data == "status":
            await self._send_status(chat_id)
            return
        if data == "digest":
            await self._flush_digest_if_due(force=True, chat_id=chat_id)

    async def _send_start(self, chat_id: int | str) -> None:
        assert self.telegram is not None and self.tracker is not None
        try:
            user = await self.tracker.identify()
            repos_result = await self.tracker.github.list_owned_repos(include_forks=True)
            repos = repos_result.data or []
            stars = sum(int(repo.get("stargazers_count") or 0) for repo in repos)
            me = await self.telegram.get_me()
            alert = format_welcome(
                user["login"],
                followers=int(user.get("followers") or 0),
                repos=len(repos),
                stars=stars,
                bot_username=me.get("username"),
            )
        except Exception:
            log.exception("Failed to build welcome message")
            await self.telegram.send_message(
                chat_id,
                "<h2>🚀 GitSnapBot is online</h2><p>I'll send GitHub activity here automatically.</p>",
                fallback="🚀 GitSnapBot is online. I'll send GitHub activity here automatically.",
                reply_markup=self._keyboard(),
            )
            self.store.set_meta("welcome_sent", "1")
            return
        await self.send(alert, chat_id=chat_id, with_nav=True)
        self.store.set_meta("welcome_sent", "1")

    async def _send_status(self, chat_id: int | str) -> None:
        assert self.telegram is not None and self.tracker is not None and self.github is not None
        username = self.tracker.username or "unknown"
        alert = format_status(
            username,
            followers=self.tracker.follower_count,
            repos=self.tracker.repo_count,
            sent=self.store.sent_count(),
            paused=self.store.paused(),
            rate_remaining=self.github.rate_remaining,
            rate_limit=self.github.rate_limit,
            last_poll=self.tracker.last_poll_at,
            queued=self.store.digest_count(),
            next_digest=self._next_digest_label(),
        )
        await self.send(alert, chat_id=chat_id, with_nav=True)
