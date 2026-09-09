from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS followers (
                login TEXT PRIMARY KEY
            );
            CREATE TABLE IF NOT EXISTS stargazers (
                repo TEXT NOT NULL,
                login TEXT NOT NULL,
                PRIMARY KEY (repo, login)
            );
            CREATE TABLE IF NOT EXISTS watchers (
                repo TEXT NOT NULL,
                login TEXT NOT NULL,
                PRIMARY KEY (repo, login)
            );
            CREATE TABLE IF NOT EXISTS forkers (
                repo TEXT NOT NULL,
                login TEXT NOT NULL,
                PRIMARY KEY (repo, login)
            );
            CREATE TABLE IF NOT EXISTS seen_events (
                id TEXT PRIMARY KEY,
                seen_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS seen_notifications (
                id TEXT PRIMARY KEY,
                seen_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS traffic (
                repo TEXT NOT NULL,
                metric TEXT NOT NULL,
                date TEXT NOT NULL,
                count INTEGER NOT NULL,
                uniques INTEGER NOT NULL,
                PRIMARY KEY (repo, metric)
            );
            CREATE TABLE IF NOT EXISTS repo_counts (
                repo TEXT NOT NULL,
                kind TEXT NOT NULL,
                count INTEGER NOT NULL,
                PRIMARY KEY (repo, kind)
            );
            CREATE TABLE IF NOT EXISTS digest_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                actor TEXT,
                repo TEXT,
                url TEXT,
                line TEXT,
                created_at REAL NOT NULL
            );
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def get_int_meta(self, key: str) -> int | None:
        raw = self.get_meta(key)
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def is_bootstrapped(self) -> bool:
        return self.get_meta("bootstrapped") == "1"

    def mark_bootstrapped(self) -> None:
        self.set_meta("bootstrapped", "1")

    def chat_id(self) -> str | None:
        return self.get_meta("telegram_chat_id")

    def set_chat_id(self, chat_id: str) -> None:
        self.set_meta("telegram_chat_id", str(chat_id))

    def paused(self) -> bool:
        return self.get_meta("paused") == "1"

    def set_paused(self, paused: bool) -> None:
        self.set_meta("paused", "1" if paused else "0")

    def sent_count(self) -> int:
        return int(self.get_meta("sent_count") or "0")

    def increment_sent(self, n: int = 1) -> None:
        self.set_meta("sent_count", str(self.sent_count() + n))

    def get_followers(self) -> set[str]:
        rows = self.conn.execute("SELECT login FROM followers").fetchall()
        return {row["login"] for row in rows}

    def replace_followers(self, logins: set[str]) -> None:
        self.conn.execute("DELETE FROM followers")
        self.conn.executemany(
            "INSERT INTO followers(login) VALUES (?)",
            [(login,) for login in logins],
        )
        self.conn.commit()

    def get_stargazers(self, repo: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT login FROM stargazers WHERE repo = ?", (repo,)
        ).fetchall()
        return {row["login"] for row in rows}

    def replace_stargazers(self, repo: str, logins: set[str]) -> None:
        self.conn.execute("DELETE FROM stargazers WHERE repo = ?", (repo,))
        self.conn.executemany(
            "INSERT INTO stargazers(repo, login) VALUES (?, ?)",
            [(repo, login) for login in logins],
        )
        self.conn.commit()

    def add_stargazer(self, repo: str, login: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO stargazers(repo, login) VALUES (?, ?)",
            (repo, login),
        )
        self.conn.commit()

    def get_watchers(self, repo: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT login FROM watchers WHERE repo = ?", (repo,)
        ).fetchall()
        return {row["login"] for row in rows}

    def replace_watchers(self, repo: str, logins: set[str]) -> None:
        self.conn.execute("DELETE FROM watchers WHERE repo = ?", (repo,))
        self.conn.executemany(
            "INSERT INTO watchers(repo, login) VALUES (?, ?)",
            [(repo, login) for login in logins],
        )
        self.conn.commit()

    def get_forkers(self, repo: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT login FROM forkers WHERE repo = ?", (repo,)
        ).fetchall()
        return {row["login"] for row in rows}

    def replace_forkers(self, repo: str, logins: set[str]) -> None:
        self.conn.execute("DELETE FROM forkers WHERE repo = ?", (repo,))
        self.conn.executemany(
            "INSERT INTO forkers(repo, login) VALUES (?, ?)",
            [(repo, login) for login in logins],
        )
        self.conn.commit()

    def has_actor_baseline(self, repo: str, kind: str) -> bool:
        return self.get_repo_count(repo, f"{kind}_listed") == 1

    def has_event(self, event_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_events WHERE id = ?", (event_id,)
        ).fetchone()
        return row is not None

    def mark_event(self, event_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_events(id, seen_at) VALUES (?, ?)",
            (event_id, time.time()),
        )
        self.conn.commit()

    def prune_events(self, keep: int = 1500) -> None:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM seen_events").fetchone()
        if row["n"] <= keep * 2:
            return
        self.conn.execute(
            """
            DELETE FROM seen_events WHERE id IN (
                SELECT id FROM seen_events ORDER BY seen_at ASC LIMIT ?
            )
            """,
            (row["n"] - keep,),
        )
        self.conn.commit()

    def has_notification(self, notification_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen_notifications WHERE id = ?", (notification_id,)
        ).fetchone()
        return row is not None

    def mark_notification(self, notification_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO seen_notifications(id, seen_at) VALUES (?, ?)",
            (notification_id, time.time()),
        )
        self.conn.commit()

    def get_traffic(self, repo: str, metric: str) -> tuple[str, int, int] | None:
        row = self.conn.execute(
            "SELECT date, count, uniques FROM traffic WHERE repo = ? AND metric = ?",
            (repo, metric),
        ).fetchone()
        if not row:
            return None
        return row["date"], int(row["count"]), int(row["uniques"])

    def set_traffic(self, repo: str, metric: str, date: str, count: int, uniques: int) -> None:
        self.conn.execute(
            """
            INSERT INTO traffic(repo, metric, date, count, uniques)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(repo, metric) DO UPDATE SET
                date = excluded.date,
                count = excluded.count,
                uniques = excluded.uniques
            """,
            (repo, metric, date, count, uniques),
        )
        self.conn.commit()

    def get_repo_count(self, repo: str, kind: str) -> int | None:
        row = self.conn.execute(
            "SELECT count FROM repo_counts WHERE repo = ? AND kind = ?",
            (repo, kind),
        ).fetchone()
        return int(row["count"]) if row else None

    def set_repo_count(self, repo: str, kind: str, count: int) -> None:
        self.conn.execute(
            """
            INSERT INTO repo_counts(repo, kind, count)
            VALUES (?, ?, ?)
            ON CONFLICT(repo, kind) DO UPDATE SET count = excluded.count
            """,
            (repo, kind, count),
        )
        self.conn.commit()

    def queue_digest(self, items: list[dict[str, str | None]]) -> None:
        if not items:
            return
        now = time.time()
        self.conn.executemany(
            """
            INSERT INTO digest_items(kind, actor, repo, url, line, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    item.get("kind") or "activity",
                    item.get("actor"),
                    item.get("repo"),
                    item.get("url"),
                    item.get("line"),
                    now,
                )
                for item in items
            ],
        )
        self.conn.commit()

    def list_digest_items(self) -> list[dict[str, str | None]]:
        rows = self.conn.execute(
            "SELECT kind, actor, repo, url, line, created_at FROM digest_items ORDER BY id ASC"
        ).fetchall()
        return [
            {
                "kind": row["kind"],
                "actor": row["actor"],
                "repo": row["repo"],
                "url": row["url"],
                "line": row["line"],
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def digest_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM digest_items").fetchone()
        return int(row["n"]) if row else 0

    def clear_digest_items(self) -> None:
        self.conn.execute("DELETE FROM digest_items")
        self.conn.commit()

    def last_digest_at(self) -> float | None:
        raw = self.get_meta("last_digest_at")
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def set_last_digest_at(self, timestamp: float) -> None:
        self.set_meta("last_digest_at", str(timestamp))
