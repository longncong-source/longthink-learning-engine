"""Knowledge-graph endpoints feeding the observability web UI (/ui).

The graph view models the Second Brain as an entity graph:
    project --< memory      (belongs_to)
    project --< document    (has_document)
    document --< memory     (chunk_of, via metadata.document_id)
The First Brain connection is surfaced through node ``origin`` (source or
metadata.via of each memory) plus the /v1/graph/status embedding-server probe.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends

from cloud.app.config import get_settings
from cloud.app.db import get_repository
from cloud.app.security import require_api_key

router = APIRouter(prefix="/v1/graph", tags=["graph"])

_STARTED_AT = time.monotonic()
_PAGE_SIZE = 500
_MAX_MEMORIES = 2000


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None if value is None else str(value)


def _memory_origin(record: Any) -> str | None:
    metadata = getattr(record, "metadata", {}) or {}
    via = metadata.get("via")
    if via:
        return f"first-brain:{via}"
    if record.source == "user-explicit":
        return "first-brain"
    return record.source or "second-brain:api"


def _collect_memories(repo: Any, limit: int, project_id: str | None) -> tuple[list[Any], bool]:
    """Page through memories up to ``limit``; returns (records, truncated)."""
    collected: list[Any] = []
    offset = 0
    while len(collected) < limit and offset < _MAX_MEMORIES + _PAGE_SIZE:
        page = repo.list_memories(
            limit=min(_PAGE_SIZE, limit - len(collected)),
            offset=offset,
            project_id=project_id,
            memory_type=None,
        )
        if not page:
            return collected, offset >= _MAX_MEMORIES
        collected.extend(page)
        offset += _PAGE_SIZE
        if len(page) < _PAGE_SIZE:
            return collected, False
    return collected[:limit], True


def _build_graph(project_id: UUID | None, max_memories: int) -> dict[str, Any]:
    settings = get_settings()
    repo = get_repository(settings)
    project_filter = str(project_id) if project_id else None

    projects = repo.list_projects(limit=_PAGE_SIZE)
    if project_filter:
        projects = [p for p in projects if str(p.id) == project_filter]
    documents = repo.list_documents(limit=_PAGE_SIZE, project_id=project_filter)
    memories, truncated = _collect_memories(repo, max(1, min(max_memories, _MAX_MEMORIES)), project_filter)

    nodes: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []

    for p in projects:
        nodes.append(
            {
                "id": f"p:{p.id}",
                "kind": "project",
                "label": p.name,
                "status": p.status,
                "description": p.description,
                "created_at": _iso(p.created_at),
                "updated_at": _iso(p.updated_at),
            }
        )
    project_ids = {f"p:{p.id}" for p in projects}

    for d in documents:
        metadata = getattr(d, "metadata", {}) or {}
        nodes.append(
            {
                "id": f"d:{d.id}",
                "kind": "document",
                "label": d.title or d.filename,
                "filename": d.filename,
                "mime_type": d.mime_type,
                "pages": metadata.get("pages"),
                "project_id": d.project_id,
                "created_at": _iso(d.created_at),
            }
        )
        if d.project_id and f"p:{d.project_id}" in project_ids:
            links.append({"source": f"p:{d.project_id}", "target": f"d:{d.id}", "kind": "has_document"})
    document_ids = {f"d:{d.id}" for d in documents}

    by_type: dict[str, int] = {}
    for m in memories:
        by_type[m.type] = by_type.get(m.type, 0) + 1
        metadata = getattr(m, "metadata", {}) or {}
        document_ref = metadata.get("document_id")
        nodes.append(
            {
                "id": f"m:{m.id}",
                "kind": "memory",
                "type": m.type,
                "label": m.title,
                "importance": m.importance,
                "confidence": m.confidence,
                "summary": m.summary,
                "origin": _memory_origin(m),
                "project_id": m.project_id,
                "document_id": document_ref,
                "created_at": _iso(m.created_at),
                "updated_at": _iso(m.updated_at),
            }
        )
        if m.project_id and f"p:{m.project_id}" in project_ids:
            links.append({"source": f"m:{m.id}", "target": f"p:{m.project_id}", "kind": "belongs_to"})
        if document_ref and f"d:{document_ref}" in document_ids:
            links.append({"source": f"m:{m.id}", "target": f"d:{document_ref}", "kind": "chunk_of"})

    stats = {
        "projects": len(projects),
        "memories_returned": len(memories),
        "documents": len(documents),
        "memories_by_type": by_type,
        "truncated": truncated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return {"nodes": nodes, "links": links, "stats": stats}


@router.get("", dependencies=[Depends(require_api_key)])
def knowledge_graph(
    max_memories: int = 800,
    project_id: UUID | None = None,
) -> dict[str, Any]:
    """Nodes + links of the knowledge graph for visualization clients."""
    return _build_graph(project_id, max_memories)


def _embedding_status() -> dict[str, Any]:
    settings = get_settings()
    info: dict[str, Any] = {
        "provider": settings.embedding_provider,
        "model": settings.embedding_model,
        "dimension": settings.embedding_dimension,
        "base_url": None,
        "reachable": True,
    }
    if settings.embedding_provider == "hash":
        info["note"] = "offline deterministic provider"
        return info

    base = settings.embedding_base_url.rstrip("/")
    info["base_url"] = base
    path = "/api/tags" if settings.embedding_provider == "ollama" else "/models"
    try:
        with httpx.Client(timeout=1.5) as client:
            response = client.get(f"{base}{path}")
        info["reachable"] = response.status_code < 500
    except Exception:  # noqa: BLE001 - status probe must never raise
        info["reachable"] = False
    return info


@router.get("/status", dependencies=[Depends(require_api_key)])
def graph_status() -> dict[str, Any]:
    """Lightweight JSON status for dashboards (backend, embeddings, counts)."""
    settings = get_settings()
    repo = get_repository(settings)

    projects = repo.list_projects(limit=_PAGE_SIZE)
    documents = repo.list_documents(limit=_PAGE_SIZE)
    memories, truncated = _collect_memories(repo, _MAX_MEMORIES, None)

    by_type: dict[str, int] = {}
    first_brain_writes = 0
    for m in memories:
        by_type[m.type] = by_type.get(m.type, 0) + 1
        origin = _memory_origin(m)
        if origin == "first-brain" or (origin or "").startswith("first-brain:"):
            first_brain_writes += 1

    return {
        "app": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "backend": repo.backend_name,
        "uptime_seconds": int(time.monotonic() - _STARTED_AT),
        "embedding": _embedding_status(),
        "counts": {
            "projects": len(projects),
            "documents": len(documents),
            "memories": len(memories),
            "memories_by_type": by_type,
            "first_brain_writes": first_brain_writes,
        },
        "truncated": truncated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
