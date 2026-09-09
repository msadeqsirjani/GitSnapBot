from pathlib import Path

from gitsnapbot.store import Store


def test_store_roundtrip(tmp_path: Path) -> None:
    store = Store(tmp_path / "test.db")
    assert store.is_bootstrapped() is False
    store.replace_followers({"a", "b"})
    assert store.get_followers() == {"a", "b"}
    store.replace_stargazers("me/repo", {"octocat"})
    assert store.get_stargazers("me/repo") == {"octocat"}
    store.add_stargazer("me/repo", "hubot")
    assert store.get_stargazers("me/repo") == {"octocat", "hubot"}
    store.replace_forkers("me/repo", {"forker"})
    assert store.get_forkers("me/repo") == {"forker"}
    store.mark_event("1")
    assert store.has_event("1") is True
    store.set_traffic("me/repo", "views", "2026-01-01T00:00:00Z", 10, 4)
    traffic = store.get_traffic("me/repo", "views")
    assert traffic == ("2026-01-01T00:00:00Z", 10, 4)
    store.mark_bootstrapped()
    assert store.is_bootstrapped() is True
    store.set_chat_id("99")
    assert store.chat_id() == "99"
    store.queue_digest(
        [{"kind": "star", "actor": "octocat", "repo": "me/repo", "url": None, "line": "starred"}]
    )
    assert store.digest_count() == 1
    store.clear_digest_items()
    assert store.digest_count() == 0
    store.close()
