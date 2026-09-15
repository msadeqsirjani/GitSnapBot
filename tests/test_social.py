from pathlib import Path

from gitsnapbot.messages import format_deleted, format_new_fork, format_unfork
from gitsnapbot.pending import PendingCommit
from gitsnapbot.social import actors_from_events
from gitsnapbot.store import Store


def test_actors_from_events_names_newest_watchers() -> None:
    events = [
        {"type": "WatchEvent", "actor": {"login": "new"}},
        {"type": "ForkEvent", "actor": {"login": "forker"}},
        {"type": "WatchEvent", "actor": {"login": "old"}},
        {"type": "WatchEvent", "actor": {"login": "new"}},
    ]
    assert actors_from_events(events, "WatchEvent", 1) == ["new"]
    assert actors_from_events(events, "WatchEvent", 5) == ["new", "old"]
    assert actors_from_events(events, "ForkEvent", 2) == ["forker"]


def test_deleted_and_unfork_cards() -> None:
    deleted = format_deleted("ghost", 10)
    assert deleted.kind == "deleted"
    assert "ghost" in deleted.text
    fork = format_new_fork("octocat", "me/repo", 2)
    assert fork.kind == "fork"
    unfork = format_unfork("octocat", "me/repo", 1)
    assert unfork.kind == "unfork"
    assert "Fork removed" in unfork.text


def test_pending_commit_waits_until_apply(tmp_path: Path) -> None:
    store = Store(tmp_path / "t.db")
    pending = PendingCommit()
    pending.followers = {"a"}
    pending.stargazers["me/repo"] = {"octocat"}
    pending.forkers["me/repo"] = {"hubot"}
    pending.repo_counts[("me/repo", "stars")] = 1
    pending.repo_counts[("me/repo", "stargazers_listed")] = 1
    pending.boot = True
    assert store.get_followers() == set()
    pending.apply(store)
    assert store.get_followers() == {"a"}
    assert store.get_stargazers("me/repo") == {"octocat"}
    assert store.get_forkers("me/repo") == {"hubot"}
    assert store.has_actor_baseline("me/repo", "stargazers") is True
    assert store.is_bootstrapped() is True
    store.close()
