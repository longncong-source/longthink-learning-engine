"""Memory endpoints (spec sections 8/10/30)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from cloud.app import metrics
from cloud.app.db import get_repository
from cloud.app.errors import NotFoundError
from cloud.app.schemas import (
    MemoryCreate,
    MemoryImportResponse,
    MemoryOut,
    MemoryType,
    MemoryWriteResponse,
    SearchRequest,
    SearchResponse,
)
from cloud.app.security import require_api_key
from cloud.app.services import audit_service
from cloud.app.services.memory_import import import_memories
from cloud.app.services.memory_service import record_to_out, search_memories, upsert_memory

router = APIRouter(prefix="/v1/memory", tags=["memory"])


@router.get("", response_model=list[MemoryOut])
def list_memories(
    limit: int = 20,
    offset: int = 0,
    project_id: UUID | None = None,
    type: str | None = None,  # noqa: A002 - query param name follows API convention
    _api_key: str = Depends(require_api_key),
) -> list[MemoryOut]:
    repo = get_repository()
    records = repo.list_memories(
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
        project_id=str(project_id) if project_id else None,
        memory_type=type,
    )
    return [record_to_out(r) for r in records]


@router.post("", response_model=MemoryWriteResponse, status_code=201)
def write_memory(payload: MemoryCreate, _api_key: str = Depends(require_api_key)) -> MemoryWriteResponse:
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
    _api_key: str = Depends(require_api_key),
) -> MemoryImportResponse:
    """Bulk-convert a file (json/jsonl/csv/md/txt) into memories for agent consumption."""
    if project_id:
        if get_repository().get_project(str(project_id)) is None:
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
def search_memory(payload: SearchRequest, _api_key: str = Depends(require_api_key)) -> SearchResponse:
    return search_memories(payload)


@router.get("/{memory_id}", response_model=MemoryOut)
def get_memory(memory_id: UUID, _api_key: str = Depends(require_api_key)) -> MemoryOut:
    record = get_repository().get_memory(str(memory_id))
    if record is None:
        raise NotFoundError(f"Memory {memory_id} not found")
    return record_to_out(record)


@router.delete("/{memory_id}", status_code=204)
def delete_memory(memory_id: UUID, _api_key: str = Depends(require_api_key)) -> Response:
    deleted = get_repository().delete_memory(str(memory_id))
    if not deleted:
        raise NotFoundError(f"Memory {memory_id} not found")
    return Response(status_code=204)
