"""Document endpoints (spec sections 31/32): upload, list, get, delete.

Uploads are multipart; text is extracted server-side (PDF page numbers preserved),
chunked semantically, embedded, and mirrored into searchable memories.
"""

from __future__ import annotations

import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile

from cloud.app.db import get_repository
from cloud.app.errors import DomainError, NotFoundError, PayloadTooLargeError, ValidationError
from cloud.app.schemas import (
    DocumentChunkOut,
    DocumentContentResponse,
    DocumentIngestResponse,
    DocumentOut,
    FolderUploadItem,
    FolderUploadResponse,
)
from cloud.app.security import require_api_key
from cloud.app.services.document_service import (
    delete_document,
    document_to_dict,
    get_document_content,
    ingest_document,
)

router = APIRouter(prefix="/v1/documents", tags=["documents"])

MAX_FOLDER_FILES = 100


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


@router.post("/upload-folder", response_model=FolderUploadResponse, status_code=201)
def upload_folder(
    files: list[UploadFile] = File(...),
    paths: str = Form(..., description="JSON array of relative paths, same order as files"),
    project_id: UUID | None = Form(default=None),
    root: str | None = Form(default=None, max_length=200),
    _api_key: str = Depends(require_api_key),
) -> FolderUploadResponse:
    """Upload a whole folder tree into one project.

    The UI sends every file with its `webkitRelativePath`; the tree is
    preserved in each document's `source` (`root/relative/path`) so RAG
    citations keep folder context. Each file goes through the same
    extract → chunk → embed → mirror pipeline as single upload.
    """
    try:
        rel_paths = json.loads(paths)
    except (json.JSONDecodeError, TypeError) as e:
        raise ValidationError(f"paths must be a JSON array: {e}") from e
    if not isinstance(rel_paths, list) or len(rel_paths) != len(files):
        raise ValidationError(
            f"paths length ({len(rel_paths) if isinstance(rel_paths, list) else '?'}) "
            f"must match files length ({len(files)})"
        )
    if len(files) > MAX_FOLDER_FILES:
        raise PayloadTooLargeError(f"max {MAX_FOLDER_FILES} files per folder upload")

    def _clean(p: str) -> str:
        # keep tree context, drop traversal / absolute prefixes
        parts = [seg for seg in str(p).replace("\\", "/").split("/") if seg not in ("", ".", "..")]
        return "/".join(parts)[:400] or "untitled"

    items: list[FolderUploadItem] = []
    total_chunks = 0
    for upload, rel in zip(files, rel_paths):
        rel_clean = _clean(rel)
        source = f"{root.strip('/')}/{rel_clean}" if root else rel_clean
        source = source[:500]
        try:
            data = upload.file.read()
            result = ingest_document(
                filename=upload.filename or rel_clean.split("/")[-1],
                data=data,
                project_id=str(project_id) if project_id else None,
                source=source,
            )
            total_chunks += result["chunks_indexed"]
            items.append(
                FolderUploadItem(
                    filename=upload.filename or rel_clean,
                    path=rel_clean,
                    document_id=result["document"]["id"],
                    chunks_indexed=result["chunks_indexed"],
                )
            )
        except DomainError as e:
            items.append(FolderUploadItem(filename=upload.filename or rel_clean, path=rel_clean, error=e.message[:200]))
        except Exception as e:  # noqa: BLE001 - per-file isolation
            items.append(FolderUploadItem(filename=upload.filename or rel_clean, path=rel_clean, error=str(e)[:200]))
    succeeded = sum(1 for i in items if not i.error)
    return FolderUploadResponse(
        project_id=project_id,
        root=root,
        total_files=len(files),
        succeeded=succeeded,
        failed=len(items) - succeeded,
        total_chunks=total_chunks,
        items=items,
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = 50,
    project_id: UUID | None = None,
    q: str | None = None,
    _api_key: str = Depends(require_api_key),
) -> list[DocumentOut]:
    """Tìm file gốc: lọc theo tên file / tiêu đề / cây thư mục (source), + project."""
    rows = get_repository().list_documents(
        limit=max(1, min(limit, 500)),
        project_id=str(project_id) if project_id else None,
        query=(q or "").strip() or None,
    )
    return [DocumentOut(**document_to_dict(r)) for r in rows]


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
def get_document_content_by_id(
    document_id: UUID, max_chunks: int = 500, _api_key: str = Depends(require_api_key)
) -> DocumentContentResponse:
    """Truy xuất file: metadata + toàn bộ chunks theo thứ tự để đọc/xem lại."""
    result = get_document_content(str(document_id), max_chunks=max_chunks)
    return DocumentContentResponse(
        document=DocumentOut(**result["document"]),
        chunks=[DocumentChunkOut(**c) for c in result["chunks"]],
        chunk_count=result["chunk_count"],
    )


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
