from __future__ import annotations

from dataclasses import dataclass, field

from gitsnapbot.store import Store


@dataclass
class PendingCommit:
    """Snapshot writes that must wait until Telegram delivery succeeds."""

    followers: set[str] | None = None
    stargazers: dict[str, set[str] | None] = field(default_factory=dict)
    forkers: dict[str, set[str] | None] = field(default_factory=dict)
    watchers: dict[str, set[str]] = field(default_factory=dict)
    repo_counts: dict[tuple[str, str], int] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    notifications: list[str] = field(default_factory=list)
    traffic: list[tuple[str, str, str, int, int]] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    boot: bool = False

    def apply(self, store: Store, *, events_keep: int = 1500) -> None:
        if self.followers is not None:
            store.replace_followers(self.followers)
        for repo, logins in self.stargazers.items():
            store.replace_stargazers(repo, logins or set())
        for repo, logins in self.forkers.items():
            store.replace_forkers(repo, logins or set())
        for repo, logins in self.watchers.items():
            store.replace_watchers(repo, logins)
        for (repo, kind), count in self.repo_counts.items():
            store.set_repo_count(repo, kind, count)
        for event_id in self.events:
            store.mark_event(event_id)
        for notification_id in self.notifications:
            store.mark_notification(notification_id)
        for repo, metric, date, count, uniques in self.traffic:
            store.set_traffic(repo, metric, date, count, uniques)
        for key, value in self.meta.items():
            store.set_meta(key, value)
        if self.boot:
            store.mark_bootstrapped()
        store.prune_events(keep=events_keep)
