"""Lightweight in-process metrics (Prometheus text exposition, spec section 41 Phase 7).

Counters are process-local (single-worker deployments). For horizontal scaling,
swap this module for a shared store later - interface kept intentionally tiny.
"""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_COUNTERS: dict[str, float] = {}
_STARTED_AT = time.monotonic()


def _key(name: str, labels: dict[str, str] | None) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


def inc(name: str, labels: dict[str, str] | None = None, value: float = 1.0) -> None:
    with _LOCK:
        _COUNTERS[_key(name, labels)] = _COUNTERS.get(_key(name, labels), 0.0) + value


def snapshot(backend: str = "unknown") -> str:
    """Render Prometheus text format (version 0.0.4)."""
    with _LOCK:
        pairs = sorted(_COUNTERS.items())
    lines = [
        "# HELP fsb_build_info Second Brain build information",
        "# TYPE fsb_build_info gauge",
        f'fsb_build_info{{backend="{backend}"}} 1',
        "# HELP fsb_uptime_seconds Process uptime in seconds",
        "# TYPE fsb_uptime_seconds gauge",
        f"fsb_uptime_seconds {time.monotonic() - _STARTED_AT:.0f}",
    ]
    current_name = None
    for key, value in pairs:
        metric_name = key.split("{")[0]
        if metric_name != current_name:
            lines.append(f"# TYPE {metric_name} counter")
            current_name = metric_name
        lines.append(f"{key} {value:.0f}")
    return "\n".join(lines) + "\n"


def reset() -> None:
    global _STARTED_AT
    with _LOCK:
        _COUNTERS.clear()
        _STARTED_AT = time.monotonic()
