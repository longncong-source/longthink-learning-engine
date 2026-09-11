"""Admin endpoints (spec sections 25/41): audit trail + Prometheus metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse

from cloud.app import metrics
from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.errors import ForbiddenError
from cloud.app.identity import tool_allowed
from cloud.app.security import require_identity
from cloud.app.services import audit_service

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get("/audit")
def list_audit(
    limit: int = 50,
    identity: Identity | None = Depends(require_identity),
) -> dict:
    """Audit trail: closed mode requires the 'admin.audit' tool (Admin/BGD)."""
    if not tool_allowed(identity, "admin.audit"):
        actor = identity.user if identity else "open"
        raise ForbiddenError(f"Tool 'admin.audit' not granted to '{actor}'")
    return {"events": audit_service.recent(limit=limit)}


@router.get("/metrics")
def admin_metrics(
    identity: Identity | None = Depends(require_identity),
) -> PlainTextResponse:
    """Prometheus metrics: closed mode requires 'admin.metrics' (Admin/BGD)."""
    if not tool_allowed(identity, "admin.metrics"):
        actor = identity.user if identity else "open"
        raise ForbiddenError(f"Tool 'admin.metrics' not granted to '{actor}'")
    settings = get_settings()
    backend = get_repository(settings).backend_name
    return PlainTextResponse(metrics.snapshot(backend=backend),
                             media_type="text/plain; version=0.0.4; charset=utf-8")
