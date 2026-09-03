"""Pydantic API schemas - Second Brain MVP (spec sections 5, 8, 10, 30, 37, 46-49).

Phase 8: Obsidian Knowledge Layer Integration (spec section 46-49).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MemoryType(str, Enum):
    semantic = "semantic"
    episodic = "episodic"
    procedural = "procedural"
    decision = "decision"
    lesson = "lesson"
    project = "project"
    document = "document"
    task = "task"
    preference = "preference"


# ---------------------------------------------------------------- memories


class MemoryCreate(BaseModel):
    project_id: UUID | None = None
    user_id: UUID | None = None
    type: MemoryType = MemoryType.semantic
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20000)
    summary: str | None = Field(default=None, max_length=4000)
    source: str | None = Field(default=None, max_length=500)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    project_id: UUID | None = None
    type: MemoryType
    title: str
    content: str
    summary: str | None = None
    source: str | None = None
    importance: float
    confidence: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryWriteResponse(BaseModel):
    memory: MemoryOut
    deduplicated: bool = False
    redaction_count: int = 0


class MemoryImportError(BaseModel):
    index: int
    error: str


class MemoryImportResponse(BaseModel):
    format: str
    total_parsed: int
    created: int
    deduplicated: int
    redaction_count: int
    memory_ids: list[str] = Field(default_factory=list)
    errors: list[MemoryImportError] = Field(default_factory=list)


class SearchFilters(BaseModel):
    type: str | list[str] | None = None
    min_importance: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    project_id: UUID | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    filters: SearchFilters = Field(default_factory=SearchFilters)


class ScoreBreakdown(BaseModel):
    semantic: float
    keyword: float
    importance: float
    recency: float


class SearchResultItem(BaseModel):
    id: UUID
    project_id: UUID | None = None
    type: MemoryType
    title: str
    content: str
    summary: str | None = None
    score: float
    scores: ScoreBreakdown
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SearchResponse(BaseModel):
    query: str
    total: int
    results: list[SearchResultItem]


# ---------------------------------------------------------------- projects


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None = None
    name: str
    description: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------- documents


class DocumentOut(BaseModel):
    id: UUID
    user_id: UUID | None = None
    project_id: UUID | None = None
    filename: str
    title: str | None = None
    source: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class DocumentIngestResponse(BaseModel):
    document: DocumentOut
    chunks_indexed: int


class FolderUploadItem(BaseModel):
    filename: str
    path: str = Field(description="Relative path inside the uploaded folder tree")
    document_id: UUID | None = None
    chunks_indexed: int = 0
    error: str | None = None


class FolderUploadResponse(BaseModel):
    project_id: UUID | None = None
    root: str | None = None
    total_files: int
    succeeded: int
    failed: int
    total_chunks: int
    items: list[FolderUploadItem]


# ---------------------------------------------------------------- obsidian (Phase 8)


class ObsidianSyncRequest(BaseModel):
    file: str = Field(..., description="Relative path in vault, e.g. '04_Lessons/vendor-delay.md'")
    content: str = Field(..., description="Full markdown content with frontmatter")
    project_id: UUID | None = None
    default_type: MemoryType = MemoryType.semantic
    source: str | None = Field(default=None, max_length=500)


class ObsidianSyncResponse(BaseModel):
    status: str  # indexed | skipped | error
    memory_id: str | None = None
    deduplicated: bool = False
    redaction_count: int = 0
    reason: str | None = None
    error: str | None = None


class ObsidianVaultSyncRequest(BaseModel):
    vault_path: str = Field(..., description="Absolute path to Obsidian vault root")
    project_id: UUID | None = None
    default_type: MemoryType = MemoryType.semantic
    source: str | None = Field(default=None, max_length=500)


class ObsidianVaultSyncItem(BaseModel):
    file: str
    status: str
    memory_id: str | None = None
    deduplicated: bool = False
    redaction_count: int = 0
    reason: str | None = None
    error: str | None = None


class ObsidianVaultSyncResponse(BaseModel):
    total_files: int
    synced: int
    skipped: int
    errors: int
    items: list[ObsidianVaultSyncItem]
