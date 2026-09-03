"""Document ingestion pipeline (spec sections 31-33).

extract pages -> semantic-aware chunks (per page, page numbers preserved) ->
embed each chunk -> store document_chunks AND mirror every chunk as a
type="document" memory so the existing hybrid search serves RAG out of the box.
"""

from __future__ import annotations

from typing import Any

from cloud.app.config import Settings, get_settings
from cloud.app.db import (
    BaseRepository,
    DocumentChunkRecord,
    DocumentRecord,
    MemoryRecord,
    get_repository,
)
from cloud.app.embeddings import embed_text
from cloud.app.errors import NotFoundError, PayloadTooLargeError
from cloud.app.metrics import inc as metric_inc
from cloud.app.services.audit_service import record as audit_record
from cloud.app.services.chunker import chunk_page_text, estimate_tokens
from cloud.app.services.classify import classify_knowledge_type
from cloud.app.services.extract import extract_pages


def document_to_dict(record: DocumentRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "project_id": record.project_id,
        "filename": record.filename,
        "title": record.title,
        "source": record.source,
        "mime_type": record.mime_type,
        "metadata": record.metadata,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def ingest_document(
    filename: str,
    data: bytes,
    *,
    project_id: str | None = None,
    title: str | None = None,
    source: str | None = None,
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> dict:
    s = settings or get_settings()
    repository = repo or get_repository(s)

    max_bytes = int(s.max_upload_mb * 1024 * 1024)
    if len(data) > max_bytes:
        raise PayloadTooLargeError(
            f"File exceeds {s.max_upload_mb} MB limit",
            details={"size_bytes": len(data), "limit_bytes": max_bytes},
        )
    if project_id and repository.get_project(project_id) is None:
        raise NotFoundError(f"Project {project_id} does not exist")

    extraction = extract_pages(filename, data)
    display_title = (title or filename)[:300]
    # Auto-recognition: file mới tự gắn knowledge_type -> ONE VECTOR PLATFORM.
    knowledge_type = classify_knowledge_type(filename, source)

    document = repository.create_document(
        DocumentRecord(
            filename=filename,
            title=display_title,
            source=source,
            mime_type=extraction.mime_type,
            metadata={
                "pages": extraction.meta.get("pages"),
                **({"knowledge_type": knowledge_type} if knowledge_type else {}),
            },
            project_id=project_id,
        )
    )

    chunks_indexed = 0
    for page in extraction.pages:
        pieces = chunk_page_text(page.text, s.chunk_size_chars, s.chunk_overlap_chars)
        for piece in pieces:
            vector = embed_text(f"{display_title}\n{piece}", s)
            memory = repository.create_memory(
                MemoryRecord(
                    type="document",
                    title=display_title,
                    content=piece,
                    summary=f"page {page.number}" if page.number else None,
                    source=f"document:{filename}",
                    importance=s.documents_importance,
                    confidence=s.documents_confidence,
                    metadata={
                        "document_id": document.id,
                        "filename": filename,
                        "page": page.number,
                        "chunk_index": chunks_indexed,
                        **({"knowledge_type": knowledge_type} if knowledge_type else {}),
                    },
                    project_id=project_id,
                    embedding=vector,
                )
            )
            repository.create_document_chunk(
                DocumentChunkRecord(
                    document_id=document.id,
                    chunk_index=chunks_indexed,
                    content=piece,
                    token_count=estimate_tokens(piece),
                    metadata={"memory_id": memory.id, "page": page.number},
                    embedding=vector,
                )
            )
            chunks_indexed += 1

    metric_inc("fsb_documents_ingested_total")
    metric_inc("fsb_document_chunks_total", value=float(chunks_indexed))
    audit_record(
        "document.ingest",
        result_count=chunks_indexed,
        detail={"filename": filename},
    )

    return {"document": document_to_dict(document), "chunks_indexed": chunks_indexed}


def get_document_content(
    document_id: str,
    *,
    max_chunks: int = 500,
    repo: BaseRepository | None = None,
) -> dict:
    """Reconstruct a document for viewing: metadata + ordered chunks."""
    repository = repo or get_repository()
    record = repository.get_document(document_id)
    if record is None:
        raise NotFoundError(f"Document {document_id} not found")
    chunks = repository.list_document_chunks(document_id, limit=max_chunks)
    return {
        "document": document_to_dict(record),
        "chunks": chunks,
        "chunk_count": len(chunks),
    }


def delete_document(
    document_id: str,
    *,
    repo: BaseRepository | None = None,
) -> dict:
    """Remove a document together with its chunks and mirrored memories."""
    repository = repo or get_repository()
    result = repository.delete_document(document_id)
    if result["chunks_removed"] == 0 and result["memories_removed"] == 0:
        raise NotFoundError(f"Document {document_id} not found")
    total_removed = int(result["chunks_removed"]) + int(result["memories_removed"])
    metric_inc("fsb_documents_deleted_total")
    audit_record("document.delete", result_count=total_removed)
    return result
