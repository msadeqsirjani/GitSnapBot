from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from gitsnapbot.config import Config
from gitsnapbot.github_api import Forbidden, GitHubClient
from gitsnapbot.messages import (
    Alert,
    format_deleted,
    format_event,
    format_follow,
    format_fork_count_delta,
    format_new_fork,
    format_notification,
    format_star,
    format_star_count_delta,
    format_traffic,
    format_unfollow,
    format_unfork,
    format_unstar,
    format_unwatch,
    format_watch,
    format_welcome,
    is_relevant_event,
)
from gitsnapbot.pending import PendingCommit
from gitsnapbot.social import SOCIAL_EVENT_TYPES, actors_from_events
from gitsnapbot.store import Store

log = logging.getLogger("gitsnapbot.tracker")

FetchActors = Callable[[str], Awaitable[set[str]]]


class Tracker:
    def __init__(self, config: Config, github: GitHubClient, store: Store) -> None:
        self.config = config
        self.github = github
        self.store = store
        self.username: str | None = None
        self.owners: set[str] = set()
        self.follower_count = 0
        self.repo_count = 0
        self.star_total = 0
        self.last_poll_at: str | None = None
        self._last_traffic_at = 0.0
        self._last_watcher_reconcile = 0.0
        self._lookups = 0
        self._backfills = 0

    async def identify(self, pending: PendingCommit | None = None) -> dict[str, Any]:
        result = await self.github.get_authenticated_user(etag=self.store.get_meta("etag:user"))
        if result.not_modified:
            login = self.store.get_meta("user_login") or ""
            self.username = login
            self.owners = {login.lower(), *self.config.github_orgs} if login else set(self.config.github_orgs)
            self.follower_count = int(self.store.get_meta("user_followers") or 0)
            log.info("GitHub profile unchanged  @%s  followers=%s", login, self.follower_count)
            return {"login": login, "followers": self.follower_count, "_not_modified": True}
        user = result.data
        login = user["login"]
        if self.config.github_username and self.config.github_username != login.lower():
            log.warning(
                "GITHUB_USERNAME=%s does not match token user %s; tracking the token user",
                self.config.github_username,
                login,
            )
        self.username = login
        self.owners = {login.lower(), *self.config.github_orgs}
        self.follower_count = int(user.get("followers") or 0)
        if pending is not None:
            if result.etag:
                pending.meta["etag:user"] = result.etag
            pending.meta["user_login"] = login
            pending.meta["user_followers"] = str(self.follower_count)
        log.info("Authenticated as @%s  followers=%s", login, self.follower_count)
        return user

    async def poll(self) -> tuple[list[Alert], PendingCommit]:
        pending = PendingCommit()
        pending.boot = not self.store.is_bootstrapped()
        self._lookups = 0
        self._backfills = 0
        self.github.reset_poll_stats()
        started = time.monotonic()
        if pending.boot:
            log.info("First run — taking a silent baseline so existing activity is not reported")
        else:
            log.info("Poll started")

        user = await self.identify(pending)
        username = user["login"]
        self.follower_count = int(user.get("followers") or 0)

        repos_result = await self.github.list_owned_repos(
            include_forks=True,
            etag=self.store.get_meta("etag:repos"),
        )
        social_repos: list[dict[str, Any]] | None
        repos: list[dict[str, Any]]
        if repos_result.not_modified:
            social_repos = None
            self.repo_count = int(self.store.get_meta("repo_count") or 0)
            self.star_total = int(self.store.get_meta("star_total") or 0)
            repos = []
            log.info(
                "Repository list unchanged  repos=%s  stars=%s",
                self.repo_count,
                self.star_total,
            )
        else:
            owned = repos_result.data or []
            if repos_result.etag:
                pending.meta["etag:repos"] = repos_result.etag
            social_repos = list(owned)
            if self.config.include_owned_forks:
                repos = list(owned)
            else:
                repos = [repo for repo in owned if not repo.get("fork")]
            seen = {repo["full_name"] for repo in repos}
            for org in self.config.github_orgs:
                try:
                    org_repos = await self.github.list_org_repos(org, self.config.include_owned_forks)
                except Exception:
                    log.exception("Failed to list repos for org %s", org)
                    continue
                for repo in org_repos:
                    if repo["full_name"] not in seen:
                        repos.append(repo)
                        social_repos.append(repo)
                        seen.add(repo["full_name"])
            self.repo_count = len(repos)
            self.star_total = sum(int(repo.get("stargazers_count") or 0) for repo in social_repos)
            pending.meta["repo_count"] = str(self.repo_count)
            pending.meta["star_total"] = str(self.star_total)
            log.info(
                "Loaded %s owned repositories  stars=%s",
                self.repo_count,
                self.star_total,
            )

        alerts: list[Alert] = []
        alerts.extend(await self._check_followers(username, self.follower_count, pending))
        if self.config.include_events:
            alerts.extend(await self._check_events(username, pending))
        if self.config.include_notifications:
            alerts.extend(await self._check_notifications(pending))
        if social_repos is not None:
            alerts.extend(await self._check_stars_and_forks(social_repos, pending))
        if self.config.include_watchers and repos:
            alerts.extend(await self._check_watchers(repos, pending))
        if self.config.include_traffic and repos:
            alerts.extend(await self._check_traffic(repos, pending))

        self.last_poll_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        kinds: dict[str, int] = {}
        for alert in alerts:
            kinds[alert.kind] = kinds.get(alert.kind, 0) + 1
        kind_summary = ", ".join(f"{name}={n}" for name, n in sorted(kinds.items())) or "none"
        elapsed = time.monotonic() - started
        log.info(
            "Poll finished  %.2fs  events=%s  %s  github=%s calls (%s not modified)  quota=%s/%s",
            elapsed,
            len(alerts) if not pending.boot else 0,
            kind_summary if not pending.boot else "baseline",
            self.github.poll_calls,
            self.github.poll_cached,
            self.github.rate_remaining if self.github.rate_remaining is not None else "?",
            self.github.rate_limit if self.github.rate_limit is not None else "?",
        )

        if pending.boot:
            if self.store.get_meta("welcome_sent") != "1":
                pending.meta["welcome_sent"] = "1"
                alerts = [
                    format_welcome(
                        username,
                        followers=self.follower_count,
                        repos=self.repo_count,
                        stars=self.star_total,
                    )
                ]
            else:
                alerts = []
        return alerts, pending

    async def _check_followers(
        self, username: str, count: int, pending: PendingCommit
    ) -> list[Alert]:
        stored = self.store.get_followers()
        last_full = float(self.store.get_meta("followers_full_at") or 0)
        due = False
        if self.config.follower_reconcile_seconds:
            due = time.time() - last_full >= self.config.follower_reconcile_seconds
        if not pending.boot and stored and len(stored) == count and not due:
            log.debug("Follower list skipped  count unchanged (%s)", count)
            return []

        current = await self.github.list_follower_logins(username)
        pending.followers = current
        pending.meta["followers_full_at"] = str(time.time())
        self.follower_count = len(current)
        if pending.boot:
            log.info("Stored follower baseline  %s accounts", len(current))
            return []

        added = sorted(current - stored)
        removed = sorted(stored - current)
        alerts = [format_follow(login, len(current)) for login in added]
        alerts.extend(await self._classify_departures(removed, len(current)))
        if alerts:
            log.info(
                "Follower changes  +%s  -%s  now=%s",
                len(added),
                len(removed),
                len(current),
            )
        return alerts

    async def _classify_departures(self, logins: list[str], total: int) -> list[Alert]:
        alerts: list[Alert] = []
        for index, login in enumerate(logins):
            if not self.config.include_deleted_check:
                alerts.append(format_unfollow(login, total))
                continue
            if index >= self.config.max_departure_lookups_per_poll:
                alerts.append(format_unfollow(login, total))
                continue
            try:
                exists = await self.github.user_exists(login)
            except Exception:
                log.exception("Failed to classify departure %s", login)
                alerts.append(format_unfollow(login, total))
                continue
            if exists is False:
                alerts.append(format_deleted(login, total))
            else:
                alerts.append(format_unfollow(login, total))
        return alerts

    async def _check_events(self, username: str, pending: PendingCommit) -> list[Alert]:
        try:
            result = await self.github.list_received_events(
                username, etag=self.store.get_meta("etag:events")
            )
        except Exception:
            log.exception("Failed to list received events")
            return []
        if result.not_modified:
            log.debug("Activity feed unchanged")
            return []
        if result.etag:
            pending.meta["etag:events"] = result.etag
        events = result.data or []
        log.info("Activity feed  %s events received", len(events))

        alerts: list[Alert] = []
        for event in reversed(events):
            event_id = str(event.get("id") or "")
            if not event_id or self.store.has_event(event_id):
                continue
            pending.events.append(event_id)
            if pending.boot:
                continue
            if event.get("type") in SOCIAL_EVENT_TYPES:
                continue
            if not is_relevant_event(event, self.owners):
                continue
            actor = ((event.get("actor") or {}).get("login") or "").lower()
            if actor == username.lower():
                continue
            alert = format_event(event)
            if alert:
                alerts.append(alert)
        return alerts

    async def _check_notifications(self, pending: PendingCommit) -> list[Alert]:
        try:
            result = await self.github.list_notifications(etag=self.store.get_meta("etag:notifications"))
        except Exception:
            log.exception("Failed to list notifications")
            return []
        if result.not_modified:
            return []
        if result.etag:
            pending.meta["etag:notifications"] = result.etag
        notifications = result.data or []

        alerts: list[Alert] = []
        for item in notifications:
            nid = str(item.get("id") or "")
            if not nid or self.store.has_notification(nid):
                continue
            pending.notifications.append(nid)
            if pending.boot:
                continue
            repo = item.get("repository") or {}
            owner = ((repo.get("owner") or {}).get("login") or "").lower()
            reason = item.get("reason") or ""
            if owner in self.owners and reason not in {
                "mention",
                "review_requested",
                "security_alert",
                "invitation",
                "assign",
            }:
                continue
            alert = format_notification(item)
            if alert:
                alerts.append(alert)
        return alerts

    async def _check_stars_and_forks(
        self, repos: list[dict[str, Any]], pending: PendingCommit
    ) -> list[Alert]:
        alerts: list[Alert] = []
        for repo in repos:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            star_count = int(repo.get("stargazers_count") or 0)
            fork_count = int(repo.get("forks_count") or 0)
            alerts.extend(
                await self._diff_actors(
                    full_name,
                    star_count,
                    pending,
                    count_key="stars",
                    list_key="stargazers",
                    fetch=self.github.list_stargazer_logins,
                    event_type="WatchEvent",
                    format_add=format_star,
                    format_remove=format_unstar,
                    format_delta=format_star_count_delta,
                    pending_map=pending.stargazers,
                )
            )
            alerts.extend(
                await self._diff_actors(
                    full_name,
                    fork_count,
                    pending,
                    count_key="forks",
                    list_key="forkers",
                    fetch=self.github.list_forker_logins,
                    event_type="ForkEvent",
                    format_add=format_new_fork,
                    format_remove=format_unfork,
                    format_delta=format_fork_count_delta,
                    pending_map=pending.forkers,
                )
            )
        return alerts

    async def _diff_actors(
        self,
        full_name: str,
        count: int,
        pending: PendingCommit,
        *,
        count_key: str,
        list_key: str,
        fetch: FetchActors,
        event_type: str,
        format_add: Callable[..., Alert],
        format_remove: Callable[..., Alert],
        format_delta: Callable[[str, int, int], Alert],
        pending_map: dict[str, set[str] | None],
    ) -> list[Alert]:
        previous_count = self.store.get_repo_count(full_name, count_key)
        has_list = self.store.has_actor_baseline(full_name, list_key)
        stored = self.store.get_stargazers(full_name) if list_key == "stargazers" else self.store.get_forkers(full_name)
        was_list: set[str] | None = stored if has_list else None

        pending.repo_counts[(full_name, count_key)] = count
        if pending.boot:
            delta = 0
            if count == 0:
                pending_map[full_name] = set()
                pending.repo_counts[(full_name, f"{list_key}_listed")] = 1
        elif previous_count is None:
            delta = 0
        else:
            delta = count - previous_count

        fetched: set[str] | None = None
        if delta != 0:
            if (
                count <= self.config.max_actors_per_repo
                and self._lookups < self.config.max_actor_lookups_per_poll
            ):
                self._lookups += 1
                fetched = await self._try_fetch_actors(fetch, full_name)
        elif (
            pending.boot
            and was_list is None
            and count > 0
            and self._backfills < self.config.max_actor_backfills_per_poll
        ):
            self._backfills += 1
            fetched = await self._try_fetch_actors(fetch, full_name)

        if fetched is not None:
            pending_map[full_name] = fetched
            pending.repo_counts[(full_name, f"{list_key}_listed")] = 1
        elif delta != 0:
            # Stale list would lie about names on the next tick.
            pending_map[full_name] = None
            pending.repo_counts[(full_name, f"{list_key}_listed")] = 0

        if pending.boot or delta == 0:
            return []

        named: list[Alert] = []
        if fetched is not None and was_list is not None:
            added = sorted(fetched - was_list)
            removed = sorted(was_list - fetched)
            named.extend(format_add(login, full_name, len(fetched)) for login in added)
            named.extend(format_remove(login, full_name, len(fetched)) for login in removed)

        if not named and delta > 0 and self.config.include_repo_event_fallback:
            try:
                events = await self.github.list_repo_events(full_name)
            except Exception:
                log.exception("Failed to read events for %s", full_name)
                events = []
            for actor in actors_from_events(events, event_type, delta):
                named.append(format_add(actor, full_name, count))

        if named:
            return named
        return [format_delta(full_name, delta, count)]

    async def _try_fetch_actors(self, fetch: FetchActors, full_name: str) -> set[str] | None:
        try:
            return await fetch(full_name)
        except Forbidden:
            log.info("Cannot list %s for %s — using count/event fallback", fetch.__name__, full_name)
            return None
        except Exception:
            log.exception("Failed to list actors for %s", full_name)
            return None

    async def _check_watchers(
        self, repos: list[dict[str, Any]], pending: PendingCommit
    ) -> list[Alert]:
        now = time.time()
        due = False
        if self.config.watcher_reconcile_seconds:
            due = now - self._last_watcher_reconcile >= self.config.watcher_reconcile_seconds
        alerts: list[Alert] = []
        reconciled = False
        for repo in repos:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            stored = self.store.get_watchers(full_name)
            subscribers = repo.get("subscribers_count")
            need = pending.boot or due
            if not need:
                continue
            try:
                current = await self.github.list_watcher_logins(full_name)
            except Forbidden:
                if subscribers is not None:
                    pending.repo_counts[(full_name, "watchers")] = int(subscribers)
                continue
            except Exception:
                log.exception("Failed to list watchers for %s", full_name)
                continue
            pending.watchers[full_name] = current
            pending.repo_counts[(full_name, "watchers")] = len(current)
            reconciled = True
            if pending.boot:
                continue
            added = sorted(current - stored)
            removed = sorted(stored - current)
            alerts.extend(format_watch(login, full_name) for login in added)
            alerts.extend(format_unwatch(login, full_name) for login in removed)
        if reconciled:
            self._last_watcher_reconcile = now
        return alerts

    async def _check_traffic(
        self, repos: list[dict[str, Any]], pending: PendingCommit
    ) -> list[Alert]:
        now = time.time()
        if not pending.boot:
            if not self.config.traffic_interval_seconds:
                return []
            if now - self._last_traffic_at < self.config.traffic_interval_seconds:
                return []
        self._last_traffic_at = now
        alerts: list[Alert] = []
        for repo in repos:
            full_name = repo.get("full_name")
            if not full_name:
                continue
            for metric in ("views", "clones"):
                payload = await self.github.get_traffic(full_name, metric)
                if not payload:
                    continue
                points = payload.get(metric) or []
                if not points:
                    continue
                latest = points[-1]
                date = str(latest.get("timestamp") or "")
                count = int(latest.get("count") or 0)
                uniques = int(latest.get("uniques") or 0)
                previous = self.store.get_traffic(full_name, metric)
                pending.traffic.append((full_name, metric, date, count, uniques))
                if pending.boot or not date:
                    continue
                if previous and previous[0] == date:
                    continue
                if count == 0 and uniques == 0:
                    continue
                alerts.append(format_traffic(full_name, metric, date, count, uniques))
        return alerts
