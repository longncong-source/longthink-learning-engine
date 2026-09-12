"""LONGTHINK ORGANIZATION CORE — Phase 12 observability.

Metrics (in-memory, label-aware):
  org_request_count / org_request_latency_seconds
  org_authorization_denied_total / org_agent_routing_total
  org_workflow_failures_total / org_approval_latency_seconds
  org_external_core_latency_seconds / org_internal_agent_failures_total
Structured JSON logs (secrets redacted, bodies never logged).
Tracing: X-Request-ID in/out; correlation/actor/project/agent ids travel in
payloads and audit context — never secrets or personal data.
Stdlib only: no new dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid

_SECRET_RE = re.compile(
    r"sk-proj-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16}"
    r"|bearer\s+[A-Za-z0-9._~-]{8,}"
    r"|(password|passwd|api[_-]?key)\s*[:=]\s*\S+",
    re.IGNORECASE)

_lock = threading.Lock()
_counters: dict[str, int] = {}
_latencies: dict[str, list[float]] = {}


def _key(name: str, labels: dict | None) -> str:
    if not labels:
        return name
    suffix = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
    return f"{name}{{{suffix}}}"


def inc(name: str, labels: dict | None = None, amount: int = 1) -> None:
    with _lock:
        key = _key(name, labels)
        _counters[key] = _counters.get(key, 0) + amount


def observe(name: str, seconds: float,
            labels: dict | None = None) -> None:
    with _lock:
        _latencies.setdefault(_key(name, labels), []).append(seconds)


def snapshot() -> dict:
    with _lock:
        summary = {}
        for key, samples in _latencies.items():
            ordered = sorted(samples)
            summary[key] = {
                "count": len(ordered),
                "avg": sum(ordered) / len(ordered) if ordered else 0.0,
                "p50": ordered[len(ordered) // 2] if ordered else 0.0,
                "max": ordered[-1] if ordered else 0.0,
            }
        return {"counters": dict(_counters), "latencies": summary}


def reset() -> None:
    with _lock:
        _counters.clear()
        _latencies.clear()


def new_request_id() -> str:
    return uuid.uuid4().hex


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = _SECRET_RE.sub("[REDACTED]", record.getMessage())
        return json.dumps({
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": message,
        }, ensure_ascii=False)


def get_logger(name: str = "org") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(RedactingFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def timed(metric: str, labels: dict | None = None):
    """Context manager recording latency into ``metric``."""

    class _Timer:
        def __enter__(self) -> _Timer:
            self.start = time.perf_counter()
            return self

        def __exit__(self, *exc_info: object) -> None:
            observe(metric, time.perf_counter() - self.start, labels)

    return _Timer()
