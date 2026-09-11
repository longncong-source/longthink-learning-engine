"""Obsidian Knowledge Layer endpoints (Phase 8, spec sections 46-49)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import APIRouter, Depends

from cloud.app import metrics
from cloud.app.db import get_repository
from cloud.app.errors import ForbiddenError
from cloud.app.identity import check_project_id, tool_allowed
from cloud.app.schemas import (
    ObsidianSyncRequest,
    ObsidianSyncResponse,
    ObsidianVaultSyncRequest,
    ObsidianVaultSyncResponse,
)
from cloud.app.security import require_identity
from cloud.app.services.audit_service import record as audit_record
from cloud.app.services.obsidian_service import scan_vault, sync_note

if TYPE_CHECKING:
    from cloud.app.identity import Identity

router = APIRouter(prefix="/v1/obsidian", tags=["obsidian"])


def _deny_obsidian_project(identity: Identity | None, project_id: str | None) -> None:
    """Closed mode: non-BGD must target an allowed project explicitly.

    Requiring payload.project_id also neutralizes the frontmatter `project:`
    override (the service only honors frontmatter when no id is supplied).
    """
    if identity is None:
        return
    if not project_id:
        if not identity.is_bgd:
            raise ForbiddenError("project_id in your allowed scope is required")
        return
    if check_project_id(identity, project_id, get_repository()) is None:
        raise ForbiddenError("Project not in your allowed scope")


@router.post("/sync", response_model=ObsidianSyncResponse, status_code=201)
def sync_obsidian_note(
    payload: ObsidianSyncRequest,
    identity: Identity | None = Depends(require_identity),
) -> ObsidianSyncResponse:
    """Sync a single Obsidian note to Second Brain.

    Expects markdown content with YAML frontmatter. Only syncs if
    frontmatter contains `sync_to_brain: true`.
    """
    if not tool_allowed(identity, "memory.write"):
        raise ForbiddenError("Tool 'memory.write' not granted")
    _deny_obsidian_project(
        identity, str(payload.project_id) if payload.project_id else None
    )
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
    identity: Identity | None = Depends(require_identity),
) -> ObsidianVaultSyncResponse:
    """Scan an Obsidian vault and sync all eligible notes.

    Recursively walks .md files under vault_path, parses frontmatter,
    and syncs notes with sync_to_brain: true. Walking server-local paths
    is an ops action: closed mode requires 'watch.manage' (BGD/Admin).
    """
    if not tool_allowed(identity, "watch.manage"):
        raise ForbiddenError("Tool 'watch.manage' not granted")
    _deny_obsidian_project(
        identity, str(payload.project_id) if payload.project_id else None
    )
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