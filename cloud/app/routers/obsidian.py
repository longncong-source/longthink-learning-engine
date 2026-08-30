"""Obsidian Knowledge Layer endpoints (Phase 8, spec sections 46-49)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from cloud.app import metrics
from cloud.app.schemas import (
    ObsidianSyncRequest,
    ObsidianSyncResponse,
    ObsidianVaultSyncRequest,
    ObsidianVaultSyncResponse,
)
from cloud.app.security import require_api_key
from cloud.app.services.audit_service import record as audit_record
from cloud.app.services.obsidian_service import scan_vault, sync_note

router = APIRouter(prefix="/v1/obsidian", tags=["obsidian"])


@router.post("/sync", response_model=ObsidianSyncResponse, status_code=201)
def sync_obsidian_note(
    payload: ObsidianSyncRequest,
    _api_key: str = Depends(require_api_key),
) -> ObsidianSyncResponse:
    """Sync a single Obsidian note to Second Brain.

    Expects markdown content with YAML frontmatter. Only syncs if
    frontmatter contains `sync_to_brain: true`.
    """
    result = sync_note(
        file_path=payload.file,
        markdown_content=payload.content,
        project_id=str(payload.project_id) if payload.project_id else None,
        default_type=payload.default_type,
        source_override=payload.source,
    )

    if result["status"] == "indexed":
        metrics.inc("fsb_obsidian_sync_total")
        audit_record(
            "obsidian.sync",
            result_count=1,
            detail={"file": payload.file, "memory_id": result.get("memory_id")},
        )

    return ObsidianSyncResponse(**result)


@router.post("/vault-sync", response_model=ObsidianVaultSyncResponse, status_code=201)
def sync_obsidian_vault(
    payload: ObsidianVaultSyncRequest,
    _api_key: str = Depends(require_api_key),
) -> ObsidianVaultSyncResponse:
    """Scan an Obsidian vault and sync all eligible notes.

    Recursively walks .md files under vault_path, parses frontmatter,
    and syncs notes with sync_to_brain: true.
    """
    result = scan_vault(
        vault_path=payload.vault_path,
        project_id=str(payload.project_id) if payload.project_id else None,
        default_type=payload.default_type,
        source_override=payload.source,
    )

    if result["synced"] > 0:
        metrics.inc("fsb_obsidian_vault_sync_total", value=float(result["synced"]))
        audit_record(
            "obsidian.vault_sync",
            result_count=result["synced"],
            detail={
                "vault": payload.vault_path,
                "total": result["total_files"],
                "synced": result["synced"],
            },
        )

    return ObsidianVaultSyncResponse(
        total_files=result["total_files"],
        synced=result["synced"],
        skipped=result["skipped"],
        errors=result["errors"],
        items=[ObsidianVaultSyncItem(**item) for item in result["items"]],
    )