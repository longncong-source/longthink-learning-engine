"""Obsidian Knowledge Layer Integration (Phase 8).

Parses Obsidian Markdown with YAML frontmatter, applies sync rules,
and upserts memories into the Second Brain.

Frontmatter standard (spec section 4):
---
title: Vendor Delay Lesson
type: lesson
project: LNG
tags: [risk, vendor]
importance: 0.9
confidence: 0.95
created: 2026-08-25
sync_to_brain: true
---

Sync rule (spec section 6): only sync notes with sync_to_brain: true

Folder → memory type mapping (spec section 3):
- 03_Resources/  → semantic
- 01_Projects/   → project
- 04_Lessons/    → lesson
- 05_Decisions/  → decision
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from cloud.app.config import Settings, get_settings
from cloud.app.db import BaseRepository, MemoryRecord, get_repository
from cloud.app.embeddings import embed_text
from cloud.app.errors import ValidationError
from cloud.app.metrics import inc as metric_inc
from cloud.app.services.audit_service import record as audit_record
from cloud.app.services.memory_service import upsert_memory
from cloud.app.schemas import MemoryCreate, MemoryType

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)
_FOLDER_TYPE_MAP = {
    "03_resources": MemoryType.semantic,
    "01_projects": MemoryType.project,
    "04_lessons": MemoryType.lesson,
    "05_decisions": MemoryType.decision,
    "02_areas": MemoryType.semantic,
    "06_books": MemoryType.semantic,
    "07_ai_memory": MemoryType.semantic,
    "00_inbox": MemoryType.semantic,
    "08_templates": MemoryType.semantic,
    "09_archive": MemoryType.semantic,
}


@dataclass
class ParsedNote:
    frontmatter: dict[str, Any]
    content: str
    file_path: str
    folder_type: MemoryType | None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from Markdown text."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"Invalid YAML frontmatter: {exc}") from exc
    body = text[match.end():].lstrip()
    return fm, body


def infer_folder_type(file_path: str) -> MemoryType | None:
    """Map Obsidian vault folder to memory type."""
    path_lower = file_path.lower().replace("\\", "/")
    for folder, mtype in _FOLDER_TYPE_MAP.items():
        if path_lower.startswith(folder + "/") or path_lower == folder:
            return mtype
    return None


def should_sync(frontmatter: dict[str, Any]) -> bool:
    """Check sync_to_brain flag (spec section 6)."""
    return bool(frontmatter.get("sync_to_brain", False))


def extract_frontmatter_fields(fm: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize known frontmatter fields."""
    created = fm.get("created")
    if isinstance(created, datetime):
        created = created.isoformat()
    elif hasattr(created, 'isoformat'):  # date objects
        created = created.isoformat()
    return {
        "title": fm.get("title"),
        "type": fm.get("type"),
        "project": fm.get("project"),
        "tags": fm.get("tags") if isinstance(fm.get("tags"), list) else [],
        "importance": fm.get("importance"),
        "confidence": fm.get("confidence"),
        "created": created,
        "sync_to_brain": fm.get("sync_to_brain", False),
    }


def build_memory_payload(
    note: ParsedNote,
    project_id: str | None,
    settings: Settings,
    default_type: MemoryType,
    source_override: str | None,
) -> MemoryCreate:
    """Convert parsed note to MemoryCreate payload."""
    fm = note.frontmatter

    # Title: frontmatter title > derived from file path
    title = fm.get("title") or Path(note.file_path).stem.replace("-", " ").replace("_", " ").title()

    # Type: frontmatter type > folder inference > default
    type_str = fm.get("type")
    if isinstance(type_str, str):
        try:
            mtype = MemoryType(type_str.lower())
        except ValueError:
            mtype = note.folder_type or default_type
    else:
        mtype = note.folder_type or default_type

    # Project: frontmatter project > provided project_id > None
    proj_id = project_id
    if fm.get("project") and not proj_id:
        # Try to resolve project by name (handled by caller via repository)
        proj_id = fm.get("project")

    # Importance/confidence
    importance = fm.get("importance")
    if not isinstance(importance, (int, float)):
        importance = settings.documents_importance
    confidence = fm.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = settings.documents_confidence

    # Metadata: tags + original frontmatter + sync metadata
    created = fm.get("created")
    if isinstance(created, datetime):
        created = created.isoformat()
    elif hasattr(created, 'isoformat'):  # date objects
        created = created.isoformat()
    
    metadata = {
        "obsidian_path": note.file_path,
        "obsidian_folder_type": note.folder_type.value if note.folder_type else None,
        "obsidian_tags": fm.get("tags") if isinstance(fm.get("tags"), list) else [],
        "obsidian_created": created,
        "import_source": "obsidian-sync",
    }

    return MemoryCreate(
        project_id=proj_id,
        type=mtype,
        title=str(title)[:300],
        content=note.content,
        summary=None,
        source=source_override or f"obsidian:{note.file_path}",
        importance=float(importance),
        confidence=float(confidence),
        metadata=metadata,
    )


def sync_note(
    file_path: str,
    markdown_content: str,
    *,
    project_id: str | None = None,
    default_type: MemoryType = MemoryType.semantic,
    source_override: str | None = None,
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> dict[str, Any]:
    """Sync a single Obsidian note to Second Brain.

    Returns dict with status, memory_id, or error.
    """
    s = settings or get_settings()
    repository = repo or get_repository(s)

    fm, body = parse_frontmatter(markdown_content)

    if not should_sync(fm):
        return {"status": "skipped", "reason": "sync_to_brain is false or missing"}

    if not body.strip():
        return {"status": "skipped", "reason": "empty content"}

    folder_type = infer_folder_type(file_path)

    note = ParsedNote(
        frontmatter=fm,
        content=body.strip(),
        file_path=file_path,
        folder_type=folder_type,
    )

    payload = build_memory_payload(note, project_id, s, default_type, source_override)

    # Validate project if provided by name
    if payload.project_id and not isinstance(payload.project_id, str):
        pass  # already UUID
    elif payload.project_id:
        # Resolve project name to ID
        proj = repository.find_project_by_name(payload.project_id)
        if proj:
            payload.project_id = str(proj.id)
        else:
            payload.project_id = None  # fallback to no project

    record, deduplicated, redaction_count = upsert_memory(payload)

    metric_inc("fsb_obsidian_sync_total")
    audit_record(
        "obsidian.sync",
        result_count=1,
        detail={"file": file_path, "memory_id": str(record.id), "deduplicated": deduplicated},
    )

    return {
        "status": "indexed",
        "memory_id": str(record.id),
        "deduplicated": deduplicated,
        "redaction_count": redaction_count,
    }


def scan_vault(
    vault_path: str,
    *,
    project_id: str | None = None,
    default_type: MemoryType = MemoryType.semantic,
    source_override: str | None = None,
    settings: Settings | None = None,
    repo: BaseRepository | None = None,
) -> dict[str, Any]:
    """Scan an Obsidian vault and sync all eligible notes.

    Recursively walks .md files, parses frontmatter, and syncs notes
    with sync_to_brain: true.
    """
    s = settings or get_settings()
    repository = repo or get_repository(s)

    vault = Path(vault_path)
    if not vault.exists():
        raise ValidationError(f"Vault path does not exist: {vault_path}")

    md_files = list(vault.rglob("*.md"))
    results = {
        "total_files": len(md_files),
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "items": [],
    }

    for md_file in md_files:
        try:
            text = md_file.read_text(encoding="utf-8", errors="replace")
            rel_path = str(md_file.relative_to(vault))
            result = sync_note(
                rel_path,
                text,
                project_id=project_id,
                default_type=default_type,
                source_override=source_override,
                settings=s,
                repo=repository,
            )
            results["items"].append({"file": rel_path, **result})
            if result["status"] == "indexed":
                results["synced"] += 1
            else:
                results["skipped"] += 1
        except Exception as exc:
            results["errors"] += 1
            results["items"].append({"file": str(md_file), "status": "error", "error": str(exc)[:200]})

    metric_inc("fsb_obsidian_vault_sync_total", value=float(results["synced"]))
    audit_record(
        "obsidian.vault_sync",
        result_count=results["synced"],
        detail={
            "vault": vault_path,
            "total": results["total_files"],
            "synced": results["synced"],
            "skipped": results["skipped"],
            "errors": results["errors"],
        },
    )

    return results