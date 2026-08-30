"""First Brain Obsidian Integration (Phase 8/10).

Parses Obsidian Markdown with YAML frontmatter and syncs to First Brain
local store and/or Second Brain via the memory client.

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
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from local.config import BrainSettings, get_brain_settings
from local.memory_client import SecondBrainClient, WriteOutcome
from local.redaction import redact_secrets

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Map Obsidian vault folders to memory types (spec section 3)
_FOLDER_TYPE_MAP = {
    "03_resources": "semantic",
    "01_projects": "project",
    "04_lessons": "lesson",
    "05_decisions": "decision",
    "02_areas": "semantic",
    "06_books": "semantic",
    "07_ai_memory": "semantic",
    "00_inbox": "semantic",
    "08_templates": "semantic",
    "09_archive": "semantic",
    # Mid Brain specific folders (Phase 10)
    "10_conflicts": "conflict",
    "11_plans": "plan",
    "12_agents": "agent",
    "13_feedback": "feedback",
    "14_meta": "meta",
}


@dataclass
class ParsedNote:
    frontmatter: dict[str, Any]
    content: str
    file_path: str
    folder_type: str | None


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and body from Markdown text."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML frontmatter: {exc}") from exc
    body = text[match.end():].lstrip()
    return fm, body


def infer_folder_type(file_path: str) -> str | None:
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
    if isinstance(created, datetime) or hasattr(created, 'isoformat'):
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
    settings: BrainSettings,
    default_type: str = "semantic",
    source_override: str | None = None,
) -> dict[str, Any]:
    """Convert parsed note to memory payload for SecondBrainClient.write_memory."""
    fm = note.frontmatter

    # Title: frontmatter title > derived from file path
    title = fm.get("title") or Path(note.file_path).stem.replace("-", " ").replace("_", " ").title()

    # Type: frontmatter type > folder inference > default
    type_str = fm.get("type")
    if isinstance(type_str, str):
        mtype = type_str.lower()
    else:
        mtype = note.folder_type or default_type

    # Project: frontmatter project > provided project_id > None
    proj_id = project_id
    if fm.get("project") and not proj_id:
        proj_id = fm.get("project")

    # Importance/confidence
    importance = fm.get("importance")
    if not isinstance(importance, (int, float)):
        importance = 0.5  # default
    confidence = fm.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = 0.8  # default

    # Metadata: tags + original frontmatter + sync metadata
    created = fm.get("created")
    if isinstance(created, datetime) or hasattr(created, 'isoformat'):
        created = created.isoformat()

    metadata = {
        "obsidian_path": note.file_path,
        "obsidian_folder_type": note.folder_type,
        "obsidian_tags": fm.get("tags") if isinstance(fm.get("tags"), list) else [],
        "obsidian_created": created,
        "import_source": "obsidian-sync",
    }

    # Redact secrets
    title_r = redact_secrets(str(title)[:300])
    content_r = redact_secrets(note.content)
    redaction_count = title_r.count + content_r.count

    return {
        "title": title_r.text,
        "content": content_r.text,
        "type": mtype,
        "importance": float(importance),
        "confidence": float(confidence),
        "source": source_override or f"obsidian:{note.file_path}",
        "metadata": metadata,
        "project_id": proj_id,
        "redaction_count": redaction_count,
    }


def sync_note(
    file_path: str,
    markdown_content: str,
    *,
    project_id: str | None = None,
    default_type: str = "semantic",
    source_override: str | None = None,
    settings: BrainSettings | None = None,
    client: SecondBrainClient | None = None,
) -> dict[str, Any]:
    """Sync a single Obsidian note to First Brain (and optionally Second Brain).

    Returns dict with status, memory_id, or error.
    """
    s = settings or get_brain_settings()
    c = client or SecondBrainClient(s)

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
    redaction_count = payload.pop("redaction_count", 0)

    # Write to Second Brain (cloud) if policy allows
    outcome: WriteOutcome = c.write_memory(
        title=payload["title"],
        content=payload["content"],
        type=payload["type"],
        importance=payload["importance"],
        confidence=payload["confidence"],
        source=payload["source"],
        metadata=payload["metadata"],
        project_id=payload["project_id"],
        allow_cloud=True,  # Obsidian sync is explicit user action
    )

    if outcome.status == "stored":
        return {
            "status": "indexed",
            "memory_id": outcome.memory_id,
            "deduplicated": outcome.deduplicated,
            "redaction_count": redaction_count + outcome.redaction_count,
        }
    elif outcome.status == "skipped_policy":
        # Stored locally only
        return {
            "status": "local_only",
            "memory_id": None,
            "deduplicated": False,
            "redaction_count": redaction_count + outcome.redaction_count,
            "reason": "data_policy=local_only",
        }
    elif outcome.status == "queued":
        return {
            "status": "queued",
            "memory_id": None,
            "deduplicated": False,
            "redaction_count": redaction_count + outcome.redaction_count,
            "reason": "second_brain_unreachable",
        }
    else:
        return {
            "status": "error",
            "memory_id": None,
            "deduplicated": False,
            "redaction_count": redaction_count + outcome.redaction_count,
            "error": outcome.detail,
        }


def scan_vault(
    vault_path: str,
    *,
    project_id: str | None = None,
    default_type: str = "semantic",
    source_override: str | None = None,
    settings: BrainSettings | None = None,
    client: SecondBrainClient | None = None,
) -> dict[str, Any]:
    """Scan an Obsidian vault and sync all eligible notes.

    Recursively walks .md files, parses frontmatter, and syncs notes
    with sync_to_brain: true.
    """
    s = settings or get_brain_settings()
    c = client or SecondBrainClient(s)

    vault = Path(vault_path)
    if not vault.exists():
        raise FileNotFoundError(f"Vault path does not exist: {vault_path}")

    md_files = list(vault.rglob("*.md"))
    results = {
        "total_files": len(md_files),
        "synced": 0,
        "skipped": 0,
        "errors": 0,
        "local_only": 0,
        "queued": 0,
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
                client=c,
            )
            results["items"].append({"file": rel_path, **result})
            if result["status"] == "indexed":
                results["synced"] += 1
            elif result["status"] == "local_only":
                results["local_only"] += 1
            elif result["status"] == "queued":
                results["queued"] += 1
            elif result["status"] == "error":
                results["errors"] += 1
            else:
                results["skipped"] += 1
        except Exception as exc:
            results["errors"] += 1
            results["items"].append({"file": str(md_file), "status": "error", "error": str(exc)[:200]})

    return results


def sync_to_obsidian(
    file_path: str,
    markdown_content: str,
    *,
    vault_path: str | None = None,
    settings: BrainSettings | None = None,
) -> dict[str, Any]:
    """Write a markdown note to Obsidian vault (First Brain → Obsidian).

    Used for exporting First Brain memories/notes to Obsidian.
    """
    s = settings or get_brain_settings()
    vault = Path(vault_path or s.obsidian_vault_path)
    if not vault.exists():
        return {"status": "error", "error": f"Vault path does not exist: {vault}"}

    target = vault / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown_content, encoding="utf-8")

    return {"status": "written", "file": str(target)}


def export_memory_to_obsidian(
    memory: dict[str, Any],
    *,
    vault_path: str | None = None,
    folder: str = "07_ai_memory",
    settings: BrainSettings | None = None,
) -> dict[str, Any]:
    """Export a memory from First Brain to Obsidian.

    Creates a markdown file with frontmatter from memory fields.
    """
    s = settings or get_brain_settings()
    vault = Path(vault_path or s.obsidian_vault_path)
    if not vault.exists():
        return {"status": "error", "error": f"Vault path does not exist: {vault}"}

    # Build frontmatter
    fm = {
        "title": memory.get("title", "Untitled"),
        "type": memory.get("type", "semantic"),
        "project": memory.get("project_id"),
        "tags": memory.get("tags", []),
        "importance": memory.get("importance", 0.5),
        "confidence": memory.get("confidence", 0.8),
        "created": memory.get("created_at", datetime.utcnow().isoformat()),
        "sync_to_brain": False,  # Don't re-sync back
    }

    # Build markdown
    content = memory.get("content", "")
    import yaml
    fm_text = yaml.dump(fm, allow_unicode=True, sort_keys=False)
    markdown = f"---\n{fm_text}---\n\n{content}"

    # Determine file path
    safe_title = memory.get("title", "memory").replace(" ", "-").replace("/", "-")[:100]
    mem_id = memory.get("id", "new")
    file_name = f"{safe_title}-{mem_id}.md"
    file_path = f"{folder}/{file_name}"

    return sync_to_obsidian(file_path, markdown, vault_path=str(vault), settings=s)
