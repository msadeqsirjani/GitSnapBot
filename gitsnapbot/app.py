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
from gitsnapbot.features.archive import load_report, save_report
from gitsnapbot.features.brief import brief_is_due, format_daily_brief
from gitsnapbot.features.chatlock import bound_chat_id, is_allowed, should_bind
from gitsnapbot.features.preview import NON_REPORT_KINDS, plan_delivery
from gitsnapbot.features.schedule import (
    apply_schedule,
    describe_schedule,
    load_schedule,
    parse_schedule,
)
from gitsnapbot.features.tokenwatch import is_unauthorized, token_alert
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
        return bound_chat_id(self.config, self.store)

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
        if self.config.bot_signature and alert.kind not in NON_REPORT_KINDS | {"digest"}:
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
            image_url=alert.image_url,
        )
        if alert.kind not in NON_REPORT_KINDS:
            self.store.increment_sent()
        return result

    def _digest_tz(self) -> ZoneInfo:
        return load_schedule(self.store, self.config)["tz"]

    def _digest_kwargs(self) -> dict[str, Any]:
        sched = load_schedule(self.store, self.config)
        return {
            "period": sched["period"],
            "weekday": sched["weekday"],
            "hour": sched["hour"],
            "minute": sched["minute"],
            "tz": sched["tz"],
        }

    def _next_digest_label(self) -> str:
        nxt = next_digest_slot(datetime.now(self._digest_tz()), **self._digest_kwargs())
        return nxt.strftime("%a %d %b %Y %H:%M %Z")

    def _queue_alerts(self, alerts: list[Alert]) -> None:
        skip = set(NON_REPORT_KINDS) | {"digest"}
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
        preview: bool = False,
        chat_id: str | int | None = None,
    ) -> None:
        assert self.telegram is not None and self.tracker is not None
        now = datetime.now(self._digest_tz())
        last_raw = self.store.last_digest_at()
        last_sent = datetime.fromtimestamp(last_raw, tz=self._digest_tz()) if last_raw else None
        if not force and not preview and not digest_is_due(now, last_sent, **self._digest_kwargs()):
            log.debug("Weekly report not due  next=%s", self._next_digest_label())
            return
        plan = plan_delivery(preview=preview, digest_pin=self.config.digest_pin)
        log.info(
            "Preparing weekly report  preview=%s  queued=%s  period=%s",
            plan.preview,
            self.store.digest_count(),
            load_schedule(self.store, self.config)["period"],
        )
        items = self.store.list_digest_items()
        if not items:
            if plan.preview or (force and not self.config.digest_send_empty):
                await self.telegram.send_message(
                    chat_id or self.chat_id() or "",
                    "<h2>Activity report</h2><p>No new activity is queued. Collection is continuing.</p>",
                    fallback="No new activity is queued. Collection is continuing.",
                    reply_markup=self._keyboard(),
                )
                return
            if not self.config.digest_send_empty:
                log.info("Weekly slot reached with an empty queue — skipping send")
                self.store.set_last_digest_at(now.timestamp())
                self.store.set_last_brief_at(now.timestamp())
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
            username=self.tracker.username,
            preview=plan.preview,
        )
        result = await self.send(alert, chat_id=chat_id, with_nav=True)
        if plan.pin and isinstance(result, dict) and result.get("message_id"):
            try:
                await self.telegram.replace_pinned_message(
                    chat_id or self.chat_id() or "",
                    int(result["message_id"]),
                )
                log.info("Pinned the weekly report and removed previous pins")
            except TelegramError:
                log.info("Could not pin the weekly report (the bot may lack permission)")
        if plan.save_archive:
            save_report(self.store, alert)
        if plan.clear_queue:
            self.store.clear_digest_items()
        if plan.update_slot:
            self.store.set_last_digest_at(now.timestamp())
            self.store.set_last_brief_at(now.timestamp())
            self.store.set_meta("last_digest_followers", str(self.tracker.follower_count))
            self.store.set_meta("last_digest_stars", str(self.tracker.star_total))
        log.info(
            "Weekly report %s  items=%s  next=%s",
            "previewed" if plan.preview else "delivered",
            len(items),
            self._next_digest_label(),
        )

    async def _flush_daily_brief_if_due(self) -> None:
        sched = load_schedule(self.store, self.config)
        if not sched["daily_brief"]:
            return
        now = datetime.now(sched["tz"])
        last_raw = self.store.last_brief_at() or self.store.last_digest_at()
        last_sent = datetime.fromtimestamp(last_raw, tz=sched["tz"]) if last_raw else None
        if not brief_is_due(
            now, last_sent, hour=sched["hour"], minute=sched["minute"], tz=sched["tz"]
        ):
            return
        items = self.store.list_digest_items()
        alert = format_daily_brief(
            items,
            username=self.tracker.username if self.tracker else None,
            next_report=self._next_digest_label(),
        )
        await self.send(alert, with_nav=True)
        self.store.set_last_brief_at(now.timestamp())
        log.info("Daily brief delivered  queued=%s", len(items))

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
                    await self._flush_daily_brief_if_due()
                self._consecutive_failures = 0
            except TelegramError:
                log.exception("Telegram send failed; weekly report was not marked sent")
            except GitHubError as exc:
                self._consecutive_failures += 1
                log.exception("Poll failed (%s consecutive)", self._consecutive_failures)
                if is_unauthorized(exc):
                    await self._notify_token_error()
                else:
                    await self._maybe_notify_error()
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
                    text="GitSnapBot could not reach GitHub. The service will retry automatically.",
                )
            )
        except Exception:
            log.exception("Failed to send error notice")

    async def _notify_token_error(self) -> None:
        now = time.time()
        if now - self._last_error_notice < self.config.error_notice_seconds:
            return
        self._last_error_notice = now
        try:
            await self.send(token_alert())
        except Exception:
            log.exception("Failed to send token notice")

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
        bound = bound_chat_id(self.config, self.store)
        if not is_allowed(chat_id, bound):
            log.info("Ignored command from unauthorized chat %s", chat_id)
            await self.telegram.send_message(
                chat_id,
                "<p>This bot is bound to another chat.</p>",
                fallback="This bot is bound to another chat.",
                rich=True,
            )
            return
        command = BUTTON_TO_COMMAND.get(text, text.split()[0].split("@", 1)[0]).lower()
        log.info("Command %s  chat=%s", command, chat_id)
        if command == "/start":
            if should_bind(chat_id, bound):
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
                "<h2>Collection paused</h2><p>GitHub polling is stopped. No new activity will be queued until collection is resumed.</p>",
                fallback="Collection paused. GitHub polling is stopped until collection is resumed.",
                reply_markup=self._keyboard(),
            )
            return
        if command == "/resume":
            self.store.set_paused(False)
            self._logged_paused = False
            log.info("Collection resumed by user")
            await self.telegram.send_message(
                chat_id,
                "<h2>Collection resumed</h2><p>GitHub activity is being queued for the next scheduled report.</p>",
                fallback="Collection resumed. GitHub activity is being queued for the next scheduled report.",
                reply_markup=self._keyboard(),
            )
            return
        if command == "/status":
            await self._send_status(chat_id)
            return
        if command == "/digest":
            await self._flush_digest_if_due(force=True, preview=True, chat_id=chat_id)
            return
        if command == "/last":
            await self._send_last(chat_id)
            return
        if command == "/when":
            rest = text.split(maxsplit=1)
            args = rest[1] if len(rest) > 1 else ""
            await self._handle_when(chat_id, args)
            return
        await self.telegram.send_message(
            chat_id,
            "<p>Use the keyboard below, or open the command list from <b>Menu</b>.</p>",
            fallback="Use the keyboard below, or open the command list from Menu.",
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
        bound = bound_chat_id(self.config, self.store)
        if not is_allowed(chat_id, bound):
            return
        if should_bind(chat_id, bound):
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
            await self._flush_digest_if_due(force=True, preview=True, chat_id=chat_id)
            return
        if data == "last":
            await self._send_last(chat_id)

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
                "<h2>GitSnapBot</h2><p>This chat is connected. GitHub activity will be delivered here.</p>",
                fallback="GitSnapBot is connected. GitHub activity will be delivered here.",
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

    async def _send_last(self, chat_id: int | str) -> None:
        assert self.telegram is not None
        alert = load_report(self.store)
        if alert is None:
            await self.telegram.send_message(
                chat_id,
                "<p>No scheduled report has been stored yet.</p>",
                fallback="No scheduled report has been stored yet.",
                reply_markup=self._keyboard(),
            )
            return
        await self.send(alert, chat_id=chat_id, with_nav=True)

    async def _handle_when(self, chat_id: int | str, args: str) -> None:
        assert self.telegram is not None
        try:
            parsed = parse_schedule(args)
        except ValueError as exc:
            await self.telegram.send_message(
                chat_id,
                f"<p>{exc}</p>",
                fallback=str(exc),
                reply_markup=self._keyboard(),
            )
            return
        if parsed:
            apply_schedule(self.store, parsed)
            log.info("Schedule updated  %s", parsed)
        sched = load_schedule(self.store, self.config)
        body = describe_schedule(sched)
        nxt = self._next_digest_label()
        html_body = body.replace("\n", "<br/>")
        await self.telegram.send_message(
            chat_id,
            f"<h2>Schedule</h2><p>{html_body}</p><p>Next weekly report: {nxt}</p>",
            fallback=f"{body}\nNext weekly report: {nxt}",
            reply_markup=self._keyboard(),
        )
