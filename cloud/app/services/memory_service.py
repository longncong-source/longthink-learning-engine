"""Write pipeline (spec section 10) and retrieval pipeline (spec section 11).

Write: validate -> redact secrets -> verify project -> embed -> dedupe check -> store/merge.
Search: embed query -> backend hybrid search -> combine scores -> top-k context.
"""

from __future__ import annotations

from cloud.app.config import Settings, get_settings
from cloud.app.db import (
    BaseRepository,
    MemoryRecord,
    SearchParams,
    get_repository,
    weights_from_settings,
)
from cloud.app.embeddings import embed_text
from cloud.app.errors import NotFoundError, ValidationError
from cloud.app.metrics import inc as metric_inc
from cloud.app.redaction import redact_secrets
from cloud.app.schemas import (
    MemoryCreate,
    MemoryOut,
    MemoryType,
    ScoreBreakdown,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from cloud.app.services.audit_service import record as audit_record


def _redact_payload(payload: MemoryCreate) -> tuple[MemoryCreate, int]:
    title = redact_secrets(payload.title)
    content = redact_secrets(payload.content)
    summary = redact_secrets(payload.summary or "")
    total = title.count + content.count + summary.count
    data = payload.model_dump()
    data["title"] = title.text
    data["content"] = content.text
    data["summary"] = summary.text or None
    return MemoryCreate(**data), total


def upsert_memory(
    payload: MemoryCreate,
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> tuple[MemoryRecord, bool, int]:
    """Store a memory, merging into an existing near-duplicate instead of duplicating.

    Returns (record, deduplicated, redaction_count).
    """
    s = settings or get_settings()
    repository = repo or get_repository(s)

    payload, redaction_count = _redact_payload(payload)

    if payload.project_id and repository.get_project(str(payload.project_id)) is None:
        raise NotFoundError(f"Project {payload.project_id} does not exist")

    embed_input = "\n".join(filter(None, [payload.title, payload.summary, payload.content]))
    embedding = embed_text(embed_input, s)

    record = MemoryRecord(
        type=payload.type.value,
        title=payload.title,
        content=payload.content,
        summary=payload.summary,
        source=payload.source,
        importance=payload.importance,
        confidence=payload.confidence,
        metadata=payload.metadata,
        project_id=str(payload.project_id) if payload.project_id else None,
        user_id=str(payload.user_id) if payload.user_id else None,
        embedding=embedding,
    )

    # Memory quality control (spec section 35): merge near-duplicates
    neighbor = repository.nearest_neighbor(embedding, record.project_id, record.type)
    if neighbor is not None and neighbor[1] >= s.dedupe_threshold:
        existing = neighbor[0]
        merged = {
            "type": record.type,
            "title": record.title,
            "content": record.content,
            "summary": record.summary or existing.summary,
            "source": record.source or existing.source,
            "importance": max(record.importance, existing.importance),
            "confidence": max(record.confidence, existing.confidence),
            "metadata": {**existing.metadata, **record.metadata},
            "embedding": embedding,
        }
        stored, deduplicated = repository.update_memory(existing.id, merged), True
    else:
        stored, deduplicated = repository.create_memory(record), False

    metric_inc("fsb_memory_writes_total", {"result": "merged" if deduplicated else "created"})
    audit_record(
        "memory.write",
        result_count=1,
        detail={"deduplicated": deduplicated, "redactions": redaction_count},
    )
    return stored, deduplicated, redaction_count


def _normalize_types(raw: str | list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    items = [raw] if isinstance(raw, str) else list(raw)
    normalized: list[str] = []
    for item in items:
        try:
            normalized.append(MemoryType(item).value)
        except ValueError as exc:
            raise ValidationError(
                f"Invalid memory type '{item}'",
                details={"allowed": [t.value for t in MemoryType]},
            ) from exc
    return normalized or None


def search_memories(
    payload: SearchRequest,
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> SearchResponse:
    s = settings or get_settings()
    repository = repo or get_repository(s)

    query_embedding = embed_text(payload.query, s)
    filters = payload.filters

    params = SearchParams(
        query=payload.query,
        query_embedding=query_embedding,
        top_k=payload.top_k,
        project_id=str(payload.project_id) if payload.project_id else None,
        types=_normalize_types(filters.type),
        min_importance=filters.min_importance if filters.min_importance is not None else 0.0,
        metadata_filter=filters.metadata,
    )

    candidate_limit = min(s.max_candidates, max(100, payload.top_k * 20))
    scored = repository.search(params, weights_from_settings(s), s.recency_half_life_days, candidate_limit)

    results = [
        SearchResultItem(
            id=item.record.id,
            project_id=item.record.project_id,
            type=MemoryType(item.record.type),
            title=item.record.title,
            content=item.record.content,
            summary=item.record.summary,
            score=round(item.total, 4),
            scores=ScoreBreakdown(
                semantic=round(item.semantic, 4),
                keyword=round(item.keyword, 4),
                importance=round(item.importance, 4),
                recency=round(item.recency, 4),
            ),
            metadata=item.record.metadata,
            created_at=item.record.created_at,
            updated_at=item.record.updated_at,
        )
        for item in scored
    ]
    metric_inc("fsb_memory_searches_total")
    audit_record("memory.search", result_count=len(results), detail={"top_k": payload.top_k})

    return SearchResponse(query=payload.query, total=len(results), results=results)


def record_to_out(record: MemoryRecord) -> MemoryOut:
    return MemoryOut(
        id=record.id,
        user_id=record.user_id,
        project_id=record.project_id,
        type=MemoryType(record.type),
        title=record.title,
        content=record.content,
        summary=record.summary,
        source=record.source,
        importance=record.importance,
        confidence=record.confidence,
        metadata=record.metadata,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
