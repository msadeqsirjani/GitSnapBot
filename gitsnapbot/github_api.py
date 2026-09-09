from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from gitsnapbot.config import Config
from gitsnapbot.logsetup import short_url

log = logging.getLogger("gitsnapbot.github")


@dataclass(slots=True)
class FetchResult:
    data: Any
    etag: str | None = None
    not_modified: bool = False


class GitHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Forbidden(GitHubError):
    pass


def next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start + 1 : end].strip()
    return None


class GitHubClient:
    def __init__(self, client: httpx.AsyncClient, config: Config) -> None:
        self.client = client
        self.config = config
        self.token = config.github_token
        self.rate_remaining: int | None = None
        self.rate_limit: int | None = None
        self.rate_reset: int | None = None
        self.poll_calls = 0
        self.poll_cached = 0
        self.verbose_http = config.log_http

    def reset_poll_stats(self) -> None:
        self.poll_calls = 0
        self.poll_cached = 0

    def _headers(
        self,
        accept: str = "application/vnd.github+json",
        etag: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": self.config.github_api_version,
            "User-Agent": self.config.user_agent,
        }
        if etag:
            headers["If-None-Match"] = etag
        return headers

    def _store_rate(self, response: httpx.Response) -> None:
        remaining = response.headers.get("X-RateLimit-Remaining")
        limit = response.headers.get("X-RateLimit-Limit")
        reset = response.headers.get("X-RateLimit-Reset")
        if remaining is not None:
            self.rate_remaining = int(remaining)
        if limit is not None:
            self.rate_limit = int(limit)
        if reset is not None:
            self.rate_reset = int(reset)

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        allow_statuses: tuple[int, ...] = (),
        etag: str | None = None,
    ) -> httpx.Response:
        if not url.startswith("http"):
            url = self.config.github_api_url + url
        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(6):
            try:
                response = await self.client.request(
                    method,
                    url,
                    params=params,
                    headers=self._headers(accept, etag=etag),
                )
            except httpx.TransportError as exc:
                last_error = exc
                log.warning(
                    "%s %s  transport error on attempt %s (%s)",
                    method,
                    short_url(url),
                    attempt + 1,
                    exc.__class__.__name__,
                )
                await asyncio.sleep(min(2**attempt, 20))
                continue

            self._store_rate(response)
            self.poll_calls += 1
            elapsed_ms = int((time.monotonic() - started) * 1000)
            quota = ""
            if self.rate_remaining is not None and self.rate_limit is not None:
                quota = f"  quota={self.rate_remaining}/{self.rate_limit}"
            cache = ""
            if response.status_code == 304:
                self.poll_cached += 1
                cache = "  cache=hit"
            elif etag:
                cache = "  cache=miss"
            if self.verbose_http:
                log.info(
                    "%s %s  %s  %sms%s%s",
                    method,
                    short_url(url),
                    response.status_code,
                    elapsed_ms,
                    cache,
                    quota,
                )

            if response.status_code == 403:
                remaining = response.headers.get("X-RateLimit-Remaining")
                retry_after = response.headers.get("Retry-After")
                if remaining == "0" and self.rate_reset:
                    wait = max(self.rate_reset - int(time.time()), 1) + 1
                    log.warning("GitHub rate limit hit, sleeping %ss", wait)
                    await asyncio.sleep(min(wait, 120))
                    continue
                if retry_after:
                    await asyncio.sleep(min(int(retry_after), 120))
                    continue
                if response.status_code in allow_statuses:
                    return response
                raise Forbidden(
                    f"GitHub 403 for {url}: {response.text[:300]}",
                    status=403,
                )

            if response.status_code == 304:
                return response

            if response.status_code in {429, 502, 503, 504}:
                await asyncio.sleep(min(2**attempt, 20))
                continue

            if response.status_code in allow_statuses:
                return response

            if response.status_code >= 400:
                raise GitHubError(
                    f"GitHub {response.status_code} for {url}: {response.text[:400]}",
                    status=response.status_code,
                )
            return response

        raise GitHubError(f"GitHub request failed after retries: {last_error}")

    async def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        allow_statuses: tuple[int, ...] = (),
    ) -> Any:
        response = await self.request(
            "GET", url, params=params, accept=accept, allow_statuses=allow_statuses
        )
        if response.status_code in {204, 304}:
            return None
        if response.status_code in allow_statuses and response.status_code >= 400:
            return None
        return response.json()

    async def paginate(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/vnd.github+json",
        max_pages: int | None = None,
        etag: str | None = None,
    ) -> FetchResult:
        items: list[Any] = []
        query = dict(params or {})
        query.setdefault("per_page", self.config.github_per_page)
        if max_pages is None:
            max_pages = self.config.github_max_pages
        current_url = url
        current_params: dict[str, Any] | None = query
        new_etag: str | None = None
        for index in range(max_pages):
            response = await self.request(
                "GET",
                current_url,
                params=current_params,
                accept=accept,
                etag=etag if index == 0 else None,
            )
            if response.status_code == 304:
                return FetchResult(None, response.headers.get("ETag") or etag, True)
            if index == 0:
                new_etag = response.headers.get("ETag")
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubError(f"Expected list from {current_url}")
            items.extend(payload)
            nxt = next_link(response.headers.get("Link"))
            if not nxt:
                break
            current_url = nxt
            current_params = None
        return FetchResult(items, new_etag, False)

    async def get_authenticated_user(self, etag: str | None = None) -> FetchResult:
        response = await self.request("GET", "/user", etag=etag)
        new_etag = response.headers.get("ETag")
        if response.status_code == 304:
            return FetchResult(None, new_etag or etag, True)
        user = response.json()
        if not isinstance(user, dict):
            raise GitHubError("Could not load authenticated GitHub user")
        return FetchResult(user, new_etag, False)

    async def list_follower_logins(self, username: str) -> set[str]:
        result = await self.paginate(f"/users/{quote(username)}/followers")
        items = result.data or []
        return {item["login"] for item in items if item.get("login")}

    async def list_owned_repos(
        self, include_forks: bool, etag: str | None = None
    ) -> FetchResult:
        result = await self.paginate(
            "/user/repos",
            params={"affiliation": "owner", "sort": "updated"},
            etag=etag,
        )
        if result.not_modified:
            return result
        items = result.data or []
        if not include_forks:
            items = [repo for repo in items if not repo.get("fork")]
        return FetchResult(items, result.etag, False)

    async def list_org_repos(self, org: str, include_forks: bool) -> list[dict[str, Any]]:
        result = await self.paginate(f"/orgs/{quote(org)}/repos", params={"type": "all"})
        items = result.data or []
        if include_forks:
            return items
        return [repo for repo in items if not repo.get("fork")]

    async def _actor_pages(self, path: str, accept: str | None = None) -> list[Any]:
        try:
            kwargs: dict[str, Any] = {"max_pages": self.config.github_actor_max_pages}
            if accept:
                kwargs["accept"] = accept
            result = await self.paginate(path, **kwargs)
            return result.data or []
        except GitHubError as exc:
            if exc.status in {401, 403, 404}:
                raise Forbidden(str(exc), status=exc.status) from exc
            raise

    async def list_stargazer_logins(self, full_name: str) -> set[str]:
        owner, repo = full_name.split("/", 1)
        items = await self._actor_pages(
            f"/repos/{quote(owner)}/{quote(repo)}/stargazers",
            accept="application/vnd.github.star+json",
        )
        logins: set[str] = set()
        for item in items:
            if "user" in item and item["user"]:
                login = item["user"].get("login")
            else:
                login = item.get("login")
            if login:
                logins.add(login)
        return logins

    async def list_forker_logins(self, full_name: str) -> set[str]:
        owner, repo = full_name.split("/", 1)
        items = await self._actor_pages(f"/repos/{quote(owner)}/{quote(repo)}/forks")
        logins: set[str] = set()
        for item in items:
            login = ((item.get("owner") or {}).get("login"))
            if login:
                logins.add(login)
        return logins

    async def user_exists(self, login: str) -> bool | None:
        response = await self.request(
            "GET",
            f"/users/{quote(login)}",
            allow_statuses=(404,),
        )
        if response.status_code == 404:
            return False
        return True

    async def list_watcher_logins(self, full_name: str) -> set[str]:
        owner, repo = full_name.split("/", 1)
        result = await self.paginate(
            f"/repos/{quote(owner)}/{quote(repo)}/subscribers"
        )
        items = result.data or []
        return {item["login"] for item in items if item.get("login")}

    async def list_received_events(
        self, username: str, etag: str | None = None
    ) -> FetchResult:
        return await self.paginate(
            f"/users/{quote(username)}/received_events",
            params={"per_page": self.config.github_per_page},
            max_pages=self.config.github_received_event_pages,
            etag=etag,
        )

    async def list_repo_events(self, full_name: str) -> list[dict[str, Any]]:
        owner, repo = full_name.split("/", 1)
        result = await self.paginate(
            f"/repos/{quote(owner)}/{quote(repo)}/events",
            params={"per_page": self.config.github_per_page},
            max_pages=self.config.github_repo_event_pages,
        )
        return result.data or []

    async def list_notifications(self, etag: str | None = None) -> FetchResult:
        return await self.paginate(
            "/notifications",
            params={"all": "false", "participating": "true"},
            etag=etag,
        )

    async def get_traffic(self, full_name: str, metric: str) -> dict[str, Any] | None:
        owner, repo = full_name.split("/", 1)
        response = await self.request(
            "GET",
            f"/repos/{quote(owner)}/{quote(repo)}/traffic/{metric}",
            allow_statuses=(403, 404),
        )
        if response.status_code in {403, 404}:
            return None
        payload = response.json()
        return payload if isinstance(payload, dict) else None
