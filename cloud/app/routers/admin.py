"""Admin endpoints (spec sections 25/41): audit trail + Prometheus metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from cloud.app import metrics
from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.errors import ConflictError, ForbiddenError, ValidationError
from cloud.app.identity import tool_allowed
from cloud.app.security import require_identity
from cloud.app.services import audit_service
from cloud.app.services.assistant_service import (
    ProvisioningError,
    list_assistants,
    provision_assistant,
    revoke_assistant,
)

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


class AssistantCreate(BaseModel):
    user: str = Field(..., min_length=1, max_length=120, description="Tên nhân viên (vd: nguyen_van_a)")
    phong: str = Field(..., description="1 trong 6 phong_chung, hoặc bgd / admin")
    role: str = Field(..., description="nhan_vien | truong_phong | bgd | admin")
    data_policy: str = Field("selective", description="local_only | selective | cloud_allowed")
    reports: list[str] = Field(default_factory=list, description="NV trực thuộc (truong_phong)")
    rate_limit: int | None = Field(None, ge=1, description="Quota req/phút, trống = mặc định server")
    create_project: bool = Field(True, description="Tự tạo project cá nhân nv_<user>")


def _deny_provision(identity: Identity | None) -> Identity:
    """Provisioning rewrites server credentials: closed mode + assistants.manage only."""
    if identity is None:
        raise ForbiddenError("Cấp phát trợ lý yêu cầu closed-mode (ORG_ACL_JSON đang trống)")
    if not tool_allowed(identity, "assistants.manage"):
        raise ForbiddenError(f"Tool 'assistants.manage' not granted to '{identity.user}'")
    return identity


@router.get("/assistants")
def list_all_assistants(
    identity: Identity | None = Depends(require_identity),
) -> dict:
    """Danh sách trợ lý ảo (key thật không bao giờ hiện — chỉ key_hint)."""
    _deny_provision(identity)
    return {"assistants": list_assistants()}


@router.post("/assistants", status_code=201)
def create_assistant(
    payload: AssistantCreate,
    identity: Identity | None = Depends(require_identity),
) -> dict:
    """Tạo 1 trợ lý ảo: sinh key + scope theo chức năng + project cá nhân.

    Trả về api_key MỘT LẦN DUY NHẤT — Admin phải copy ngay cho nhân viên.
    Hiệu lực ngay, không cần restart (server đơn tiến trình).
    """
    actor = _deny_provision(identity)
    try:
        view = provision_assistant(
            user=payload.user,
            phong=payload.phong,
            role=payload.role,
            data_policy=payload.data_policy,
            reports=payload.reports,
            rate_limit=payload.rate_limit,
            create_project=payload.create_project,
        )
    except ProvisioningError as exc:
        msg = str(exc)
        if "đã tồn tại" in msg:
            raise ConflictError(msg) from exc
        raise ValidationError(msg) from exc
    audit_service.record(
        "assistants.create", result_count=1,
        detail={"user": view["user"], "role": view["role"], "by": actor.user},
    )
    return view


@router.delete("/assistants/{user}")
def delete_assistant(
    user: str,
    identity: Identity | None = Depends(require_identity),
) -> dict:
    """Thu hồi key của 1 trợ lý (tri thức/project giữ lại, quyền truy cập chấm dứt)."""
    actor = _deny_provision(identity)
    try:
        result = revoke_assistant(user)
    except ProvisioningError as exc:
        raise ValidationError(str(exc)) from exc
    audit_service.record(
        "assistants.revoke", result_count=1,
        detail={"user": result["user"], "by": actor.user},
    )
    return result
