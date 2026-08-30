"""Container entrypoint: wait for PostgreSQL, apply migrations, then exec uvicorn."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
WAIT_SECONDS = 60


def _wait_for_db() -> None:
    import psycopg

    deadline = time.time() + WAIT_SECONDS
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as conn:
                conn.execute("SELECT 1")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
    print(f"[container_init] database not reachable after {WAIT_SECONDS}s: {last_error}", file=sys.stderr)
    raise SystemExit(1)


def _apply_migrations() -> None:
    import psycopg

    sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        for path in sql_files:
            print(f"[container_init] applying migration {path.name}")
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()


def main() -> None:
    _wait_for_db()
    _apply_migrations()
    os.execvp(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "cloud.app.main:app", "--host", "0.0.0.0", "--port", "8000"],
    )


if __name__ == "__main__":
    main()
