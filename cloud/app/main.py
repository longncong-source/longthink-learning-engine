"""FastAPI application factory - Second Brain Memory API (MVP)."""

from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

from cloud.app import metrics
from cloud.app.config import get_settings
from cloud.app.db import get_repository, reset_repository
from cloud.app.errors import DomainError, RateLimitError
from cloud.app.routers import admin, code, comfy, documents, graph, health, lmstudio, memories, mid_brain, obsidian, odc, projects
from cloud.app.routers import code_proxy, odc_proxy
from cloud.app.security import RateLimiter, client_identity
from cloud.app.services import audit_service

logger = logging.getLogger("fsb")

_AUDIT_SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}
_UI_DIR = Path(__file__).resolve().parent / "ui"


def _audit_skipped(path: str) -> bool:
    return path in _AUDIT_SKIP_PATHS or path.startswith("/ui")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))


class ObservabilityMiddleware(BaseHTTPMiddleware):
    """request_id + latency + rate limiting + persistent audit (spec sections 25/41).

    Observability rules: never log query text, bodies, or secrets -
    only method/path/status/duration/request_id and an API-key hint.
    """

    def __init__(self, app, limiter: RateLimiter) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limiter = limiter

    async def _audit(self, *, request_id: str, identity: str, request: Request,
                     status: int, duration_ms: int) -> None:
        path = request.url.path
        if _audit_skipped(path):
            return
        metrics.inc("fsb_http_requests_total", {"code": str(status)})
        try:
            await run_in_threadpool(
                lambda: audit_service.record(
                    "http",
                    request_id=request_id,
                    api_key_hint=identity[:16],
                    method=request.method,
                    path=path,
                    status=status,
                    duration_ms=duration_ms,
                )
            )
        except Exception:  # noqa: BLE001 - audit never breaks requests
            metrics.inc("fsb_audit_write_failures_total")

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        identity = client_identity(request, request.headers.get("x-api-key"))
        start = time.perf_counter()

        def _respond(status: int, body: dict | None = None, headers: dict | None = None):
            logger.info(
                "access %s %s -> %s (%dms) rid=%s",
                request.method,
                request.url.path,
                status,
                int((time.perf_counter() - start) * 1000),
                request_id,
            )
            response = JSONResponse(status_code=status, content=body or {}, headers=headers)
            response.headers["X-Request-ID"] = request_id
            return response

        try:
            self.limiter.check(identity)
        except RateLimitError as exc:
            retry_after = str(exc.details.get("retry_after_seconds", "60"))
            duration_ms = int((time.perf_counter() - start) * 1000)
            await self._audit(request_id=request_id, identity=identity, request=request,
                              status=exc.status_code, duration_ms=duration_ms)
            return _respond(
                exc.status_code,
                {"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
                headers={"Retry-After": retry_after},
            )

        try:
            response = await call_next(request)
        except Exception:  # noqa: BLE001
            logger.exception("unhandled error rid=%s", request_id)
            metrics.inc("fsb_http_requests_total", {"code": "500"})
            return _respond(500, {"error": {"code": "internal_error", "message": "Unexpected server error"}})

        duration_ms = int((time.perf_counter() - start) * 1000)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "access %s %s -> %s (%dms) rid=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        await self._audit(
            request_id=request_id,
            identity=identity,
            request=request,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        get_repository(settings).init_schema()
        logger.info("storage backend ready (%s)", get_repository().backend_name)
    except DomainError as exc:
        # Degraded start: /health still answers; writes/searches return 503 meaningfully.
        logger.warning("storage unavailable at startup: %s", exc.message)
    yield
    reset_repository()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.version, lifespan=lifespan)
    app.add_middleware(ObservabilityMiddleware, limiter=RateLimiter(settings.rate_limit_per_minute))
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID", "Retry-After"],
        )
    app.include_router(health.router)
    app.include_router(memories.router)
    app.include_router(projects.router)
    app.include_router(documents.router)
    app.include_router(admin.router)
    app.include_router(graph.router)
    app.include_router(obsidian.router)
    app.include_router(mid_brain.router)
    app.include_router(comfy.router)
    app.include_router(code.router)
    app.include_router(lmstudio.router)
    app.include_router(odc.router)
    # Proxy OpenCode Web :4096 -> :8100/code/*  (auth handled server-side, no login popup in iframe)
    @app.api_route("/code/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _code_proxy(request: Request, path: str):
        return await code_proxy.proxy_request(request, path)
    @app.api_route("/code", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _code_proxy_root(request: Request):
        return await code_proxy.proxy_request(request, "")
    # Fallback for absolute URLs in proxied HTML (e.g. /api, /assets, /favicon) — also proxy to 4096
    @app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _api_proxy(request: Request, path: str):
        # Only proxy if this looks like OpenCode (avoid shadowing LongThink /v1/api)
        # LongThink uses /v1/*, so /api/* is safe to proxy
        return await code_proxy.proxy_request(request, f"api/{path}")
    @app.api_route("/assets/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _assets_proxy(request: Request, path: str):
        return await code_proxy.proxy_request(request, f"assets/{path}")
    # Proxy ODC Studio :3001 -> :8100/odc/* (visual orchestration RETRIEVE->THINK->STORE)
    @app.api_route("/odc/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _odc_proxy(request: Request, path: str):
        return await odc_proxy.proxy_request(request, path)
    @app.api_route("/odc", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def _odc_proxy_root(request: Request):
        return await odc_proxy.proxy_request(request, "")

    if _UI_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_UI_DIR), html=True), name="ui")
    else:  # pragma: no cover - UI folder ships with the repo
        logger.warning("UI directory missing at %s - dashboard disabled", _UI_DIR)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):  # type: ignore[no-untyped-def]
        headers = None
        retry_after = exc.details.get("retry_after_seconds")
        if isinstance(retry_after, int):
            headers = {"Retry-After": str(retry_after)}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        def _clean(errors):  # type: ignore[no-untyped-def]
            safe = []
            for err in errors:
                entry = {
                    "loc": [str(part) for part in err.get("loc", [])],
                    "msg": str(err.get("msg", "invalid")),
                    "type": str(err.get("type", "value_error")),
                }
                input_value = err.get("input")
                if isinstance(input_value, (str, int, float, bool)) or input_value is None:
                    entry["input"] = input_value
                safe.append(entry)
            return safe

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": _clean(exc.errors())},
                }
            },
        )

    return app


app = create_app()
