"""Repository abstraction (spec section 3): swappable backends behind one interface.

Backends:
    PostgresRepository - PostgreSQL + pgvector (MVP target, docker compose)
    SqliteRepository   - zero-dependency fallback so the full loop runs on any laptop
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from cloud.app.config import Settings, get_settings
from cloud.app.errors import RepositoryError
from cloud.app.textops import normalize_weights


@dataclass(slots=True)
class MemoryRecord:
    type: str
    title: str
    content: str
    summary: str | None = None
    source: str | None = None
    importance: float = 0.5
    confidence: float = 0.8
    metadata: dict = field(default_factory=dict)
    project_id: str | None = None
    user_id: str | None = None
    id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    embedding: list[float] | None = None


@dataclass(slots=True)
class ProjectRecord:
    name: str
    description: str | None = None
    status: str = "active"
    metadata: dict = field(default_factory=dict)
    user_id: str | None = None
    id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class DocumentRecord:
    filename: str
    title: str | None = None
    source: str | None = None
    mime_type: str | None = None
    metadata: dict = field(default_factory=dict)
    user_id: str | None = None
    project_id: str | None = None
    id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class DocumentChunkRecord:
    document_id: str
    chunk_index: int
    content: str
    token_count: int | None = None
    metadata: dict = field(default_factory=dict)
    embedding: list[float] | None = None
    id: str | None = None
    created_at: str | None = None


@dataclass(slots=True)
class SearchParams:
    query: str
    query_embedding: list[float]
    top_k: int = 8
    project_id: str | None = None
    types: list[str] | None = None
    min_importance: float = 0.0
    metadata_filter: dict | None = None


@dataclass(slots=True)
class ScoredMemory:
    record: MemoryRecord
    semantic: float
    keyword: float
    importance: float
    recency: float
    total: float


def weights_from_settings(settings: Settings | None = None) -> dict[str, float]:
    s = settings or get_settings()
    return normalize_weights(
        {
            "semantic": s.weight_semantic,
            "keyword": s.weight_keyword,
            "importance": s.weight_importance,
            "recency": s.weight_recency,
        }
    )


class BaseRepository(ABC):
    """Interface every storage backend implements."""

    backend_name = "abstract"

    @abstractmethod
    def init_schema(self) -> None: ...

    @abstractmethod
    def ping(self) -> bool: ...

    @abstractmethod
    def backend_info(self) -> dict: ...

    # --- memories ---
    @abstractmethod
    def create_memory(self, record: MemoryRecord) -> MemoryRecord: ...

    @abstractmethod
    def get_memory(self, memory_id: str) -> MemoryRecord | None: ...

    @abstractmethod
    def delete_memory(self, memory_id: str) -> bool: ...

    @abstractmethod
    def update_memory(self, memory_id: str, fields: dict) -> MemoryRecord: ...

    @abstractmethod
    def list_memories(
        self,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryRecord]: ...

    @abstractmethod
    def search(
        self,
        params: SearchParams,
        weights: dict[str, float],
        half_life_days: float,
        candidate_limit: int,
    ) -> list[ScoredMemory]: ...

    @abstractmethod
    def nearest_neighbor(
        self,
        embedding: list[float],
        project_id: str | None,
        memory_type: str,
    ) -> tuple[MemoryRecord, float] | None: ...

    @abstractmethod
    def count_memories(self) -> int: ...

    # --- projects ---
    @abstractmethod
    def create_project(self, record: ProjectRecord) -> ProjectRecord: ...

    @abstractmethod
    def get_project(self, project_id: str) -> ProjectRecord | None: ...

    @abstractmethod
    def find_project_by_name(self, name: str) -> ProjectRecord | None: ...

    @abstractmethod
    def list_projects(self, limit: int = 100) -> list[ProjectRecord]: ...

    @abstractmethod
    def count_projects(self) -> int: ...

    # --- documents (spec sections 31/32) ---
    @abstractmethod
    def create_document(self, record: "DocumentRecord") -> "DocumentRecord": ...

    @abstractmethod
    def get_document(self, document_id: str) -> "DocumentRecord | None": ...

    @abstractmethod
    def list_documents(
        self,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list["DocumentRecord"]: ...

    @abstractmethod
    def delete_document(self, document_id: str) -> dict:
        """Delete document + its chunks + mirrored chunk memories.

        Returns {"chunks_removed": int, "memories_removed": int}.
        """

    @abstractmethod
    def create_document_chunk(self, record: "DocumentChunkRecord") -> "DocumentChunkRecord": ...

    @abstractmethod
    def count_documents(self) -> int: ...

    @abstractmethod
    def count_document_chunks(self) -> int: ...

    # --- audit trail (spec sections 25/41) ---
    @abstractmethod
    def record_audit(self, event: dict) -> None: ...

    @abstractmethod
    def list_audit(self, limit: int = 50) -> list[dict]: ...


_REPO_LOCK = threading.Lock()
_REPO_SINGLETON: BaseRepository | None = None


def build_repository(settings: Settings) -> BaseRepository:
    if settings.memory_db_backend == "sqlite":
        from cloud.app.repositories.sqlite_repo import SqliteRepository

        return SqliteRepository(settings.sqlite_path)
    if settings.memory_db_backend == "postgres":
        from cloud.app.repositories.postgres_repo import PostgresRepository

        return PostgresRepository(settings.database_url)
    raise RepositoryError(f"Unknown MEMORY_DB_BACKEND: {settings.memory_db_backend}")


def get_repository(settings: Settings | None = None) -> BaseRepository:
    global _REPO_SINGLETON
    with _REPO_LOCK:
        if _REPO_SINGLETON is None:
            _REPO_SINGLETON = build_repository(settings or get_settings())
        return _REPO_SINGLETON


def reset_repository() -> None:
    global _REPO_SINGLETON
    with _REPO_LOCK:
        if _REPO_SINGLETON is not None:
            close_method = getattr(_REPO_SINGLETON, "close", None)
            if callable(close_method):
                close_method()
        _REPO_SINGLETON = None
