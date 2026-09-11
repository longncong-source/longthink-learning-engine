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
    WatchedFolder,
    WatchRegisterRequest,
    WatchScanResponse,
    WatchStatusResponse,
)
from typing import TYPE_CHECKING

from cloud.app.errors import ForbiddenError
from cloud.app.identity import (
    allowed_project_id_set,
    check_project_id,
    is_foreign_personal,
    tool_allowed,
)
from cloud.app.security import require_identity
from cloud.app.services import watcher
from cloud.app.services.document_service import (
    delete_document,
    document_to_dict,
    get_document_content,
    ingest_document,
)

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/documents", tags=["documents"])

MAX_FOLDER_FILES = 100


def _deny_doc_project(
    identity: Identity | None,
    project_id: str | None,
    *,
    write: bool = False,
) -> None:  # type: ignore[no-untyped-def]
    from cloud.app.db import get_repository as _get_repo

    if identity is None:
        return
    if not project_id:
        if not identity.is_bgd:
            raise ForbiddenError("project_id is required (unscoped access is BGD-only)")
        return
    repo = _get_repo()
    name = check_project_id(identity, project_id, repo)
    if name is None:
        raise ForbiddenError("Project not in your allowed scope")
    if write and is_foreign_personal(identity, name):
        raise ForbiddenError("Cannot write into another person's personal project")


@router.post("/upload", response_model=DocumentIngestResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    project_id: UUID | None = Form(default=None),
    title: str | None = Form(default=None, max_length=300),
    source: str | None = Form(default=None, max_length=500),
    identity: Identity | None = Depends(require_identity),
) -> DocumentIngestResponse:
    if not tool_allowed(identity, "doc.upload"):
        raise ForbiddenError("Tool 'doc.upload' not granted")
    _deny_doc_project(identity, str(project_id) if project_id else None, write=True)
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
        deduplicated=bool(result.get("deduplicated")),
    )


@router.post("/upload-folder", response_model=FolderUploadResponse, status_code=201)
def upload_folder(
    files: list[UploadFile] = File(...),
    paths: str = Form(..., description="JSON array of relative paths, same order as files"),
    project_id: UUID | None = Form(default=None),
    root: str | None = Form(default=None, max_length=200),
    identity: Identity | None = Depends(require_identity),
) -> FolderUploadResponse:
    """Upload a whole folder tree into one project.

    The UI sends every file with its `webkitRelativePath`; the tree is
    preserved in each document's `source` (`root/relative/path`) so RAG
    citations keep folder context. Each file goes through the same
    extract → chunk → embed → mirror pipeline as single upload.
    """
    if not tool_allowed(identity, "doc.upload"):
        raise ForbiddenError("Tool 'doc.upload' not granted")
    _deny_doc_project(identity, str(project_id) if project_id else None, write=True)
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


@router.post("/watch", response_model=WatchedFolder, status_code=201)
def register_watch(
    body: WatchRegisterRequest,
    identity: Identity | None = Depends(require_identity),
) -> WatchedFolder:
    """Đăng ký thư mục để tự động index (NEW/MODIFIED/DELETED, incremental).

    Server-local paths: BGD/Admin only in closed mode (watch.manage).
    """
    if not tool_allowed(identity, "watch.manage"):
        raise ForbiddenError("Tool 'watch.manage' not granted")
    _deny_doc_project(identity, str(body.project_id) if body.project_id else None, write=True)
    try:
        entry = watcher.register_folder(
            body.path, str(body.project_id) if body.project_id else None
        )
    except ValueError as e:
        raise ValidationError(str(e)) from e
    return WatchedFolder(**entry)


@router.get("/watch", response_model=WatchStatusResponse)
def watch_status(identity: Identity | None = Depends(require_identity)) -> WatchStatusResponse:
    # Folder paths are server-local: closed mode requires a provisioned identity.
    st = watcher.status()
    return WatchStatusResponse(
        running=st["running"],
        poll_seconds=st["poll_seconds"],
        folders=[WatchedFolder(**f) for f in st["folders"]],
        last_scan=st["last_scan"],
    )


@router.post("/watch/scan", response_model=WatchScanResponse)
def watch_scan_now(
    identity: Identity | None = Depends(require_identity),
) -> WatchScanResponse:
    """Chạy scan incremental ngay (không đợi poll)."""
    if not tool_allowed(identity, "watch.manage"):
        raise ForbiddenError("Tool 'watch.manage' not granted")
    summary = watcher.scan_once()
    return WatchScanResponse(**summary)


@router.delete("/watch", status_code=204)
def unregister_watch(
    path: str,
    identity: Identity | None = Depends(require_identity),
) -> Response:
    if not tool_allowed(identity, "watch.manage"):
        raise ForbiddenError("Tool 'watch.manage' not granted")
    if not watcher.unregister_folder(path):
        raise NotFoundError(f"Watched folder not found: {path}")
    return Response(status_code=204)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    limit: int = 50,
    project_id: UUID | None = None,
    q: str | None = None,
    identity: Identity | None = Depends(require_identity),
) -> list[DocumentOut]:
    """Tìm file gốc: lọc theo tên file / tiêu đề / cây thư mục (source), + project."""
    if not tool_allowed(identity, "doc.read"):
        raise ForbiddenError("Tool 'doc.read' not granted")
    pid = str(project_id) if project_id else None
    if pid:
        # Scoped read: pre-check. Unscoped: post-filtered below.
        _deny_doc_project(identity, pid)
    rows = get_repository().list_documents(
        limit=max(1, min(limit, 500)),
        project_id=pid,
        query=(q or "").strip() or None,
    )
    allowed = allowed_project_id_set(identity, get_repository())
    if allowed is not None:
        rows = [r for r in rows if str(r.project_id) in allowed]
    return [DocumentOut(**document_to_dict(r)) for r in rows]


@router.get("/{document_id}/content", response_model=DocumentContentResponse)
def get_document_content_by_id(
    document_id: UUID,
    max_chunks: int = 500,
    identity: Identity | None = Depends(require_identity),
) -> DocumentContentResponse:
    """Truy xuất file: metadata + toàn bộ chunks theo thứ tự để đọc/xem lại."""
    if not tool_allowed(identity, "doc.read"):
        raise ForbiddenError("Tool 'doc.read' not granted")
    result = get_document_content(str(document_id), max_chunks=max_chunks)
    _deny_doc_project(identity, result["document"].get("project_id"))
    return DocumentContentResponse(
        document=DocumentOut(**result["document"]),
        chunks=[DocumentChunkOut(**c) for c in result["chunks"]],
        chunk_count=result["chunk_count"],
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: UUID,
    identity: Identity | None = Depends(require_identity),
) -> DocumentOut:
    if not tool_allowed(identity, "doc.read"):
        raise ForbiddenError("Tool 'doc.read' not granted")
    record = get_repository().get_document(str(document_id))
    if record is None:
        raise NotFoundError(f"Document {document_id} not found")
    _deny_doc_project(identity, record.project_id)
    return DocumentOut(**document_to_dict(record))


@router.delete("/{document_id}", status_code=204)
def delete_document_by_id(
    document_id: UUID,
    identity: Identity | None = Depends(require_identity),
) -> Response:
    # Delete is high-impact: BGD-only by default (hỏi trước khi xóa).
    if not tool_allowed(identity, "doc.delete"):
        raise ForbiddenError("Tool 'doc.delete' not granted")
    record = get_repository().get_document(str(document_id))
    if record is None:
        raise NotFoundError(f"Document {document_id} not found")
    _deny_doc_project(identity, record.project_id)
    delete_document(str(document_id))
    return Response(status_code=204)
