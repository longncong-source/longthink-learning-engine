"""Memory endpoints (spec sections 8/10/30)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from cloud.app import metrics
from cloud.app.db import get_repository
from cloud.app.errors import NotFoundError
from cloud.app.schemas import (
    KnowledgePlatformResponse,
    MemoryCreate,
    MemoryImportResponse,
    MemoryOut,
    MemoryType,
    MemoryWriteResponse,
    SearchRequest,
    SearchResponse,
)
from typing import TYPE_CHECKING

from cloud.app.errors import ForbiddenError
from cloud.app.identity import (
    allowed_project_id_set,
    check_project_id,
    is_foreign_personal,
    tool_allowed,
)
from cloud.app.security import require_api_key, require_identity
from cloud.app.services import audit_service
from cloud.app.services.memory_import import import_memories
from cloud.app.services.memory_service import record_to_out, search_memories, upsert_memory

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/memory", tags=["memory"])


def _deny_tool(identity: Identity | None, tool: str) -> None:
    if not tool_allowed(identity, tool):
        actor = identity.user if identity else "open"
        raise ForbiddenError(f"Tool '{tool}' not granted to '{actor}'")


def _deny_project(identity: Identity | None, project_id: str | None, repo) -> None:  # type: ignore[no-untyped-def]
    """Pre-check a scoped request. Unscoped writes/reads in closed mode need BGD."""
    if identity is None:
        return
    if not project_id:
        if not identity.is_bgd:
            raise ForbiddenError("project_id is required (unscoped access is BGD-only)")
        return
    if check_project_id(identity, project_id, repo) is None:
        raise ForbiddenError("Project not in your allowed scope")


@router.get("/knowledge-domains", response_model=KnowledgePlatformResponse)
def knowledge_domains(_api_key: str = Depends(require_api_key)) -> KnowledgePlatformResponse:
    """ONE VECTOR PLATFORM: 8 logical knowledge domains + trạng thái trên memory types."""
    from cloud.app.services.knowledge_domains import platform_status

    return KnowledgePlatformResponse(**platform_status())


@router.get("", response_model=list[MemoryOut])
def list_memories(
    limit: int = 20,
    offset: int = 0,
    project_id: UUID | None = None,
    type: str | None = None,  # noqa: A002 - query param name follows API convention
    identity: Identity | None = Depends(require_identity),
) -> list[MemoryOut]:
    _deny_tool(identity, "memory.search")
    repo = get_repository()
    pid = str(project_id) if project_id else None
    if pid:
        # Scoped read: pre-check. Unscoped: post-filtered below (chung+phong+rieng).
        _deny_project(identity, pid, repo)
    records = repo.list_memories(
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
        project_id=pid,
        memory_type=type,
    )
    allowed = allowed_project_id_set(identity, repo)
    if allowed is not None:
        records = [r for r in records if str(r.project_id) in allowed]
    return [record_to_out(r) for r in records]


@router.post("", response_model=MemoryWriteResponse, status_code=201)
def write_memory(
    payload: MemoryCreate,
    identity: Identity | None = Depends(require_identity),
) -> MemoryWriteResponse:
    _deny_tool(identity, "memory.write")
    repo = get_repository()
    pid = str(payload.project_id) if payload.project_id else None
    _deny_project(identity, pid, repo)
    if identity is not None and pid:
        # truong_phong reads reports' nv_* but never writes into them.
        if is_foreign_personal(identity, check_project_id(identity, pid, repo)):
            raise ForbiddenError("Cannot write into another person's personal project")
    if identity is not None and not identity.is_admin:
        # Stamp actor hint for auditability (additive; never overwrites caller keys).
        payload.metadata.setdefault("_actor", identity.user)
        payload.metadata.setdefault("_phong", identity.phong)
    record, deduplicated, redaction_count = upsert_memory(payload)
    return MemoryWriteResponse(
        memory=record_to_out(record),
        deduplicated=deduplicated,
        redaction_count=redaction_count,
    )


@router.post("/import", response_model=MemoryImportResponse, status_code=201)
def import_memories_endpoint(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    default_type: MemoryType = Form(default=MemoryType.semantic),
    source: str | None = Form(default=None, max_length=500),
    identity: Identity | None = Depends(require_identity),
) -> MemoryImportResponse:
    """Bulk-convert a file (json/jsonl/csv/md/txt) into memories for agent consumption."""
    _deny_tool(identity, "memory.write")
    repo = get_repository()
    pid = str(project_id) if project_id else None
    _deny_project(identity, pid, repo)
    if identity is not None and pid:
        # Same rule as single writes: never bulk-import into someone's nv_*.
        if is_foreign_personal(identity, check_project_id(identity, pid, repo)):
            raise ForbiddenError("Cannot write into another person's personal project")
    if project_id:
        if repo.get_project(str(project_id)) is None:
            raise NotFoundError(f"Project {project_id} does not exist")

    data = file.file.read()
    result = import_memories(
        filename=file.filename or "untitled",
        data=data,
        project_id=str(project_id) if project_id else None,
        default_type=default_type,
        source_override=source,
    )
    metrics.inc("fsb_memory_imports_total")
    metrics.inc("fsb_memory_import_items_total", value=float(result["created"]))
    audit_service.record(
        "memory.import",
        result_count=result["created"],
        detail={
            "format": result["format"],
            "filename": (file.filename or "untitled")[:120],
            "errors": len(result["errors"]),
        },
    )
    return MemoryImportResponse(**result)


@router.post("/search", response_model=SearchResponse)
def search_memory(
    payload: SearchRequest,
    identity: Identity | None = Depends(require_identity),
) -> SearchResponse:
    _deny_tool(identity, "memory.search")
    repo = get_repository()
    pid = str(payload.project_id) if payload.project_id else None
    if pid:
        # Scoped search: pre-check. Unscoped: post-filtered below (chung+phong+rieng).
        _deny_project(identity, pid, repo)
    response = search_memories(payload)
    allowed = allowed_project_id_set(identity, repo)
    if allowed is not None:
        response.results = [r for r in response.results if str(r.project_id) in allowed]
        response.total = len(response.results)
    return response


@router.get("/{memory_id}", response_model=MemoryOut)
def get_memory(
    memory_id: UUID,
    identity: Identity | None = Depends(require_identity),
) -> MemoryOut:
    _deny_tool(identity, "memory.search")
    repo = get_repository()
    record = repo.get_memory(str(memory_id))
    if record is None:
        raise NotFoundError(f"Memory {memory_id} not found")
    _deny_project(identity, record.project_id, repo)
    return record_to_out(record)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(
    memory_id: UUID,
    identity: Identity | None = Depends(require_identity),
) -> Response:
    # Delete is high-impact: BGD-only by default (hỏi trước khi ghi/xóa).
    _deny_tool(identity, "memory.delete")
    repo = get_repository()
    record = repo.get_memory(str(memory_id))
    if record is None:
        raise NotFoundError(f"Memory {memory_id} not found")
    _deny_project(identity, record.project_id, repo)
    repo.delete_memory(str(memory_id))
    return Response(status_code=204)
