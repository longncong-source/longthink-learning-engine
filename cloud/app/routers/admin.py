"""Admin endpoints (spec sections 25/41): audit trail + Prometheus metrics."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from cloud.app import metrics
from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.security import require_api_key
from cloud.app.services import audit_service

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/audit", dependencies=[Depends(require_api_key)])
def list_audit(limit: int = 50) -> dict:
    return {"events": audit_service.recent(limit=limit)}


@router.get("/metrics", dependencies=[Depends(require_api_key)])
def admin_metrics() -> PlainTextResponse:
    settings = get_settings()
    backend = get_repository(settings).backend_name
    return PlainTextResponse(metrics.snapshot(backend=backend),
                             media_type="text/plain; version=0.0.4; charset=utf-8")
