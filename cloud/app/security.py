"""API key authentication and simple sliding-window rate limiting (spec sections 21, 26)."""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque

from fastapi import Header, Request

from typing import TYPE_CHECKING

from cloud.app.config import get_settings
from cloud.app.errors import AuthenticationError, RateLimitError

if TYPE_CHECKING:
    from cloud.app.identity import Identity


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


def require_identity(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> Identity | None:
    """Authenticated key + org identity (None in open mode).

    Raises 403 when the server runs closed mode (ORG_ACL_JSON set) but the
    valid key has no identity entry — valid key, missing provisioning.
    """
    from cloud.app.errors import ForbiddenError
    from cloud.app.identity import acl_configured, resolve_identity

    supplied = require_api_key(x_api_key, authorization)
    if not acl_configured():
        return None
    identity = resolve_identity(supplied)
    if identity is None:
        raise ForbiddenError(
            "API key has no org identity (missing from ORG_ACL_JSON) - contact Admin",
        )
    return identity


_LIMITERS_LOCK = threading.Lock()
_LIMITERS: dict[str, RateLimiter] = {}  # type: ignore[valid-type]  # defined below, filled lazily


def reset_limiters() -> None:
    """Clear per-key limiter state (tests / key rotation)."""
    with _LIMITERS_LOCK:
        _LIMITERS.clear()


def custom_limiter_for_request(request: Request) -> RateLimiter | None:  # type: ignore[valid-type]
    """Per-key quota from ORG_ACL_JSON (rate_limit). None = server default applies.

    Best-effort: any failure falls back to the default limiter, never blocks.
    """
    try:
        from cloud.app.identity import acl_configured, resolve_identity

        if not acl_configured():
            return None
        raw = request.headers.get("x-api-key")
        authz = request.headers.get("authorization")
        key = raw.strip() if raw else None
        if not key and authz and authz.lower().startswith("bearer "):
            key = authz[7:].strip()
        ident = resolve_identity(key)
        if ident is None or not ident.rate_limit:
            return None
        with _LIMITERS_LOCK:
            limiter = _LIMITERS.get(ident.hint)
            if limiter is None or limiter.limit != ident.rate_limit:
                limiter = RateLimiter(ident.rate_limit)
                _LIMITERS[ident.hint] = limiter
            return limiter
    except Exception:
        return None


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
