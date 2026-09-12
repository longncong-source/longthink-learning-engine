"""SQLite store for Organization Core Phase 01.

Own database file (default ``data/organization.sqlite3``) — never touches
cloud/local/mid_brain databases (master rule 3).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_SCHEMA_BASE = _MIGRATIONS_DIR / "0001_init.sql"

_DROP_ORDER = [
    "schema_migrations",
    "org_versions",
    "agent_executions",
    "governance_kv",
    "policy_versions",
    "project_milestones",
    "decisions",
    "issues",
    "risks",
    "audit_events",
    "policies",
    "agents",
    "assistants",
    "approvals",
    "workflow_instances",
    "workflows",
    "tasks",
    "project_assignments",
    "project_roles",
    "projects",
    "delegations",
    "person_positions",
    "person_roles",
    "role_permissions",
    "permissions",
    "roles",
    "persons",
    "positions",
    "teams",
    "departments",
    "companies",
]


class OrganizationStore:
    """Minimal SQLite repository for Phase 01 domain persistence."""

    def __init__(self, path: str = "data/organization.sqlite3") -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(self.path), check_same_thread=False)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA journal_mode=WAL")
                self._conn = conn
            return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def init_schema(self) -> None:
        """Up migration: base schema (idempotent) + pending versioned migrations."""
        conn = self.connect()
        with self._lock:
            conn.executescript(_SCHEMA_BASE.read_text(encoding="utf-8"))
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                r["version"]
                for r in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
                if path.name <= "0001_init.sql" or path.stem in applied:
                    continue
                conn.executescript(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at)"
                    " VALUES (?, datetime('now'))",
                    (path.stem,),
                )
            conn.commit()

    def drop_all(self) -> None:
        """Down migration: drop all Organization Core tables (reverse order)."""
        conn = self.connect()
        with self._lock:
            for table in _DROP_ORDER:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.commit()

    # --- generic helpers ---
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self.connect()
        with self._lock:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        conn = self.connect()
        with self._lock:
            return conn.execute(sql, params).fetchone()

    def query_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        conn = self.connect()
        with self._lock:
            return list(conn.execute(sql, params).fetchall())

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        row = self.query_one(sql, params)
        return int(row["n"]) if row else 0

    def table_names(self) -> list[str]:
        rows = self.query_all(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r["name"] for r in rows]


def encode_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def decode_json(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}
