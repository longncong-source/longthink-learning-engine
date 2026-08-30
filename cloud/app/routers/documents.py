"""Document endpoints (spec sections 31/32): upload, list, get, delete.

Uploads are multipart; text is extracted server-side (PDF page numbers preserved),
chunked semantically, embedded, and mirrored into searchable memories.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from cloud.app.db import get_repository
from cloud.app.errors import NotFoundError
from cloud.app.schemas import DocumentIngestResponse, DocumentOut
from cloud.app.security import require_api_key
from cloud.app.services.document_service import (
    delete_document,
    document_to_dict,
    ingest_document,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentIngestResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None, max_length=300),
    source: str | None = Form(default=None, max_length=500),
    _api_key: str = Depends(require_api_key),
) -> DocumentIngestResponse:
    data = file.file.read()
    result = ingest_document(
        filename=file.filename or "untitled",
        data=data,
        project_id=str(project_id) if project_id else None,
        title=title,
        source=source,
    )
    return DocumentIngestResponse(
        document=DocumentOut(**result["document"]),
        chunks_indexed=result["chunks_indexed"],
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = 50,
    project_id: UUID | None = None,
    _api_key: str = Depends(require_api_key),
) -> list[DocumentOut]:
    rows = get_repository().list_documents(
        limit=max(1, min(limit, 500)),
        project_id=str(project_id) if project_id else None,
    )
    return [DocumentOut(**document_to_dict(r)) for r in rows]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: UUID, _api_key: str = Depends(require_api_key)) -> DocumentOut:
    record = get_repository().get_document(str(document_id))
    if record is None:
        raise NotFoundError(f"Document {document_id} not found")
    return DocumentOut(**document_to_dict(record))


@router.delete("/{document_id}", status_code=204)
def delete_document_by_id(
    document_id: UUID,
    _api_key: str = Depends(require_api_key),
) -> Response:
    delete_document(str(document_id))
    return Response(status_code=204)
