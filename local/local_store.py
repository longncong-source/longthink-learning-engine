"""Local SQLite persistence for the First Brain (spec sections 16, 23, 24).

Tables:
    session_notes  - short-term local context that NEVER leaves the laptop
    pending_writes - outbox queue for memories waiting for the cloud to return
    query_cache    - TTL cache of Second Brain search responses
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_notes (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_writes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_cache (
    cache_key TEXT PRIMARY KEY,
    response TEXT NOT NULL,
    expires_at REAL NOT NULL
);
"""


class LocalStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------------------------------------------------------- session notes
    def add_note(self, kind: str, content: str) -> str:
        note_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO session_notes (id, kind, content, created_at) VALUES (?,?,?,?)",
                (note_id, kind, content, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            self._conn.commit()
        return note_id

    def list_notes(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM session_notes ORDER BY created_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------- pending writes
    def enqueue_write(self, payload: dict) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO pending_writes (payload, created_at) VALUES (?, ?)",
                (json.dumps(payload, ensure_ascii=False),
                 time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
            self._conn.commit()
        return int(cur.lastrowid)

    def pending_batch(self, limit: int = 25) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM pending_writes ORDER BY id LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_write_done(self, item_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM pending_writes WHERE id=?", (int(item_id),))
            self._conn.commit()

    def mark_write_failed(self, item_id: int, error: str, *, permanent: bool) -> None:
        """Network errors stay queued for retry; permanent 4xx drops are recorded as notes."""
        with self._lock:
            if permanent:
                self._conn.execute("DELETE FROM pending_writes WHERE id=?", (int(item_id),))
                self._conn.execute(
                    "INSERT INTO session_notes (id, kind, content, created_at) VALUES (?,?,?,?)",
                    (uuid.uuid4().hex, "dropped_write", f"item {item_id}: {error}",
                     time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                )
            else:
                self._conn.execute(
                    "UPDATE pending_writes SET attempts=attempts+1, last_error=? WHERE id=?",
                    (error[:500], int(item_id)),
                )
            self._conn.commit()

    def pending_count(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM pending_writes").fetchone()
        return int(row["c"])

    # ------------------------------------------------------------ query cache
    def cache_get(self, key: str) -> dict | None:
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT response, expires_at FROM query_cache WHERE cache_key=?", (key,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= now:
            with self._lock:
                self._conn.execute("DELETE FROM query_cache WHERE cache_key=?", (key,))
                self._conn.commit()
            return None
        try:
            data = json.loads(row["response"])
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    def cache_set(self, key: str, value: dict, ttl_seconds: float) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO query_cache (cache_key, response, expires_at) VALUES (?,?,?)",
                (key, json.dumps(value, ensure_ascii=False), time.time() + max(ttl_seconds, 1.0)),
            )
            self._conn.commit()

    def clear_cache(self) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM query_cache")
            self._conn.commit()
        return cur.rowcount
