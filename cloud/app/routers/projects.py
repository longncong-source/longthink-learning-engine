"""Project endpoints (spec sections 15/30)."""

from __future__ import annotations

from uuid import UUID

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from cloud.app.db import ProjectRecord, get_repository
from cloud.app.errors import ConflictError, ForbiddenError, NotFoundError
from cloud.app.identity import project_name_allowed, tool_allowed
from cloud.app.metrics import inc as metric_inc
from cloud.app.schemas import ProjectCreate, ProjectOut
from cloud.app.security import require_identity
from cloud.app.services.audit_service import record as audit_record

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/projects", tags=["projects"])


def _project_out(record: ProjectRecord) -> ProjectOut:
    return ProjectOut(
        id=record.id,
        user_id=record.user_id,
        name=record.name,
        description=record.description,
        status=record.status,
        metadata=record.metadata,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    limit: int = 100,
    identity: Identity | None = Depends(require_identity),
) -> list[ProjectOut]:
    if not tool_allowed(identity, "project.list"):
        raise ForbiddenError("Tool 'project.list' not granted")
    limit = max(1, min(limit, 500))
    projects = get_repository().list_projects(limit=limit)
    if identity is not None and not identity.is_bgd:
        projects = [p for p in projects if project_name_allowed(identity, p.name)]
    return [_project_out(p) for p in projects]


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    identity: Identity | None = Depends(require_identity),
) -> ProjectOut:
    if not tool_allowed(identity, "project.create"):
        raise ForbiddenError("Tool 'project.create' not granted")
    repo = get_repository()
    existing = repo.find_project_by_name(payload.name)
    if existing is not None:
        raise ConflictError(f"Project '{payload.name}' already exists", details={"id": existing.id})
    if identity is not None and not identity.is_bgd:
        if not project_name_allowed(identity, payload.name):
            raise ForbiddenError("Project name not in your allowed scope")
    record = ProjectRecord(
        name=payload.name,
        description=payload.description,
        metadata=payload.metadata,
    )
    created = repo.create_project(record)
    metric_inc("fsb_projects_created_total")
    audit_record("project.create", result_count=1, detail={"project_id": created.id})
    return _project_out(created)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: UUID,
    identity: Identity | None = Depends(require_identity),
) -> ProjectOut:
    if not tool_allowed(identity, "project.list"):
        raise ForbiddenError("Tool 'project.list' not granted")
    project = get_repository().get_project(str(project_id))
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    if identity is not None and not identity.is_bgd:
        if not project_name_allowed(identity, project.name):
            raise ForbiddenError("Project not in your allowed scope")
    return _project_out(project)
