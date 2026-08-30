"""API key authentication and simple sliding-window rate limiting (spec sections 21, 26)."""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, Request

from cloud.app.config import get_settings
from cloud.app.errors import AuthenticationError, RateLimitError


def _extract_supplied_key(x_api_key: str | None, authorization: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> str:
    """Fail-closed API key check. Accepts X-API-Key or Authorization: Bearer."""
    configured = get_settings().api_key_list
    supplied = _extract_supplied_key(x_api_key, authorization)

    if not configured:
        raise AuthenticationError("Server has no API keys configured (MEMORY_API_KEYS empty)")

    if not supplied:
        raise AuthenticationError("Missing API key (send X-API-Key header or Bearer token)")

    for key in configured:
        if hmac.compare_digest(key, supplied):
            return supplied

    raise AuthenticationError("Invalid API key")


class RateLimiter:
    """In-memory sliding window limiter keyed by API key or client host."""

    def __init__(self, limit_per_minute: int) -> None:
        self.limit = max(1, limit_per_minute)
        self.window_seconds = 60.0
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, identity: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._events[identity]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])) + 1)
                raise RateLimitError(
                    f"Rate limit of {self.limit} requests/minute exceeded",
                    details={"retry_after_seconds": retry_after},
                )
            bucket.append(now)


def client_identity(request: Request, api_key: str | None) -> str:
    if api_key:
        return f"key:{api_key[:12]}"
    return f"ip:{request.client.host if request.client else 'unknown'}"
