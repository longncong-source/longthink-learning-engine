"""Persistent audit trail (spec sections 25/41).

Records operational metadata only - never query text, bodies or secrets.
Failures are swallowed (counted in metrics) so auditing can never break a
user request.
"""

from __future__ import annotations

from typing import Any

from cloud.app.db import BaseRepository, get_repository
from cloud.app.textops import isoformat_now

_MAX_STR = 200


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:_MAX_STR]
    return value


def record(
    kind: str,
    *,
    request_id: str | None = None,
    api_key_hint: str | None = None,
    method: str | None = None,
    path: str | None = None,
    status: int | None = None,
    duration_ms: int | None = None,
    result_count: int | None = None,
    detail: dict | None = None,
    repo: BaseRepository | None = None,
) -> bool:
    """Best-effort audit write. Returns True when persisted."""
    try:
        repository = repo or get_repository()
        safe_detail = {str(k)[:50]: _clip(v) for k, v in (detail or {}).items()}
        repository.record_audit(
            {
                "ts": isoformat_now(),
                "kind": kind[:100],
                "request_id": request_id,
                "api_key_hint": api_key_hint,
                "method": method,
                "path": path,
                "status": status,
                "duration_ms": duration_ms,
                "result_count": result_count,
                "detail": safe_detail,
            }
        )
        return True
    except Exception:  # noqa: BLE001 - auditing must never break requests
        from cloud.app.metrics import inc

        inc("fsb_audit_write_failures_total")
        return False


def recent(limit: int = 50, repo: BaseRepository | None = None) -> list[dict]:
    repository = repo or get_repository()
    return repository.list_audit(limit=max(1, min(limit, 500)))
