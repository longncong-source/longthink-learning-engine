"""SQLite fallback backend - lets the full First/Second Brain loop run without Docker.

Semantics mirror the PostgreSQL/pgvector backend:
  - semantic score: cosine similarity computed in Python over candidate rows
  - keyword score : term F1 overlap (cloud.app.textops.keyword_score)
  - metadata filter: shallow key/value subset match
Intended for development/laptop use; production MVP target is PostgreSQL+pgvector.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import ClassVar

from cloud.app.db import (
    BaseRepository,
    DocumentChunkRecord,
    DocumentRecord,
    MemoryRecord,
    ProjectRecord,
    ScoredMemory,
    SearchParams,
)
from cloud.app.errors import RepositoryError
from cloud.app.textops import (
    combine_scores,
    cosine_similarity,
    isoformat_now,
    keyword_score,
    recency_score,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    name TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    project_id TEXT,
    filename TEXT NOT NULL,
    title TEXT,
    source TEXT,
    mime_type TEXT,
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content TEXT NOT NULL,
    token_count INT,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, chunk_index)
);
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    request_id TEXT,
    api_key_hint TEXT,
    method TEXT,
    path TEXT,
    status INTEGER,
    duration_ms INTEGER,
    result_count INTEGER,
    detail TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts DESC);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    project_id TEXT,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    summary TEXT,
    source TEXT,
    importance REAL NOT NULL DEFAULT 0.5,
    confidence REAL NOT NULL DEFAULT 0.8,
    metadata TEXT NOT NULL DEFAULT '{}',
    embedding TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sqlite_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_sqlite_memories_type ON memories(type);
CREATE INDEX IF NOT EXISTS idx_sqlite_memories_updated ON memories(updated_at DESC);
"""


def _now() -> str:
    return isoformat_now()


class SqliteRepository(BaseRepository):
    backend_name = "sqlite"

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error as exc:
            raise RepositoryError(f"Cannot open SQLite store at {self.path}: {exc}") from exc
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ utils
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def _dump_meta(metadata: dict) -> str:
        return json.dumps(metadata or {}, ensure_ascii=False)

    @staticmethod
    def _load_meta(raw) -> dict:
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _dump_embedding(vector: list[float] | None) -> str | None:
        if not vector:
            return None
        return json.dumps([round(float(x), 9) for x in vector])

    @staticmethod
    def _load_embedding(raw) -> list[float] | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return [float(x) for x in data] if isinstance(data, list) else None
        except json.JSONDecodeError:
            return None

    def _memory_from_row(self, row: sqlite3.Row) -> MemoryRecord:
        return MemoryRecord(
            id=row["id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            type=row["type"],
            title=row["title"],
            content=row["content"],
            summary=row["summary"],
            source=row["source"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            metadata=self._load_meta(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            embedding=self._load_embedding(row["embedding"]),
        )

    def _project_from_row(self, row: sqlite3.Row) -> ProjectRecord:
        return ProjectRecord(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row["description"],
            status=row["status"],
            metadata=self._load_meta(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ------------------------------------------------------------- lifecycle
    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def ping(self) -> bool:
        try:
            with self._lock:
                self._conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    def backend_info(self) -> dict:
        return {
            "backend": self.backend_name,
            "path": str(self.path),
            "size_bytes": self.path.stat().st_size if self.path.exists() else 0,
        }

    # --------------------------------------------------------------- memories
    def create_memory(self, record: MemoryRecord) -> MemoryRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        with self._lock:
            self._conn.execute(
                """INSERT INTO memories
                   (id, user_id, project_id, type, title, content, summary, source,
                    importance, confidence, metadata, embedding, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.id,
                    record.user_id,
                    record.project_id,
                    record.type,
                    record.title,
                    record.content,
                    record.summary,
                    record.source,
                    float(record.importance),
                    float(record.confidence),
                    self._dump_meta(record.metadata),
                    self._dump_embedding(record.embedding),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()
        return record

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._memory_from_row(row) if row else None

    def delete_memory(self, memory_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            self._conn.commit()
        return cur.rowcount > 0

    _UPDATABLE: ClassVar[set[str]] = {
        "type", "title", "content", "summary", "source",
        "importance", "confidence", "metadata", "embedding",
    }
    _COLUMN_OF: ClassVar[dict[str, str]] = {"embedding": "_dump_embedding", "metadata": "_dump_meta"}

    def update_memory(self, memory_id: str, fields: dict) -> MemoryRecord:
        clean = {k: v for k, v in fields.items() if k in self._UPDATABLE}
        if not clean:
            existing = self.get_memory(memory_id)
            if existing is None:
                raise RepositoryError(f"Memory {memory_id} not found for update")
            return existing
        sets, values = [], []
        for key, value in clean.items():
            dumper_name = self._COLUMN_OF.get(key)
            dumper = getattr(self, dumper_name) if dumper_name else None
            sets.append(f"{key}=?")
            values.append(dumper(value) if dumper else value)
        sets.append("updated_at=?")
        values.append(_now())
        values.append(memory_id)
        with self._lock:
            self._conn.execute(f"UPDATE memories SET {', '.join(sets)} WHERE id=?", values)
            self._conn.commit()
        updated = self.get_memory(memory_id)
        if updated is None:
            raise RepositoryError(f"Memory {memory_id} disappeared during update")
        return updated

    def list_memories(
        self,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryRecord]:
        sql = "SELECT * FROM memories"
        clauses, values = [], []
        if project_id:
            clauses.append("project_id=?")
            values.append(project_id)
        if memory_type:
            clauses.append("type=?")
            values.append(memory_type)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        values += [int(limit), int(offset)]
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        return [self._memory_from_row(r) for r in rows]

    def _iter_candidates(self, params: SearchParams, limit: int) -> list[MemoryRecord]:
        sql = "SELECT * FROM memories WHERE importance >= ?"
        values: list = [float(params.min_importance)]
        if params.project_id:
            sql += " AND project_id = ?"
            values.append(params.project_id)
        if params.types:
            placeholders = ",".join("?" for _ in params.types)
            sql += f" AND type IN ({placeholders})"
            values.extend(params.types)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        values.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        records = [self._memory_from_row(r) for r in rows]
        if params.metadata_filter:
            wanted = {k: v for k, v in params.metadata_filter.items()}
            records = [r for r in records if all(r.metadata.get(k) == v for k, v in wanted.items())]
        return records

    def search(
        self,
        params: SearchParams,
        weights: dict[str, float],
        half_life_days: float,
        candidate_limit: int,
    ) -> list[ScoredMemory]:
        scored: list[ScoredMemory] = []
        for record in self._iter_candidates(params, candidate_limit):
            semantic = (
                cosine_similarity(params.query_embedding, record.embedding)
                if record.embedding
                else 0.0
            )
            document = " ".join(filter(None, [record.title, record.summary, record.content]))
            keyword = keyword_score(params.query, document)
            recency = recency_score(record.updated_at or record.created_at or _now(), half_life_days)
            total = combine_scores(
                semantic=semantic,
                keyword=keyword,
                importance=record.importance,
                recency=recency,
                weights=weights,
            )
            scored.append(ScoredMemory(record, semantic, keyword, record.importance, recency, total))
        scored.sort(key=lambda s: (s.total, s.record.updated_at or ""), reverse=True)
        return scored[: params.top_k]

    def nearest_neighbor(
        self,
        embedding: list[float],
        project_id: str | None,
        memory_type: str,
    ) -> tuple[MemoryRecord, float] | None:
        best: tuple[float, MemoryRecord] | None = None
        params = SearchParams(
            query="",
            query_embedding=embedding,
            project_id=project_id,
            types=[memory_type],
            min_importance=-1.0,
            top_k=1_000_000,
        )
        for record in self._iter_candidates(params, 1_000_000):
            if not record.embedding:
                continue
            sim = cosine_similarity(embedding, record.embedding)
            if best is None or sim > best[0]:
                best = (sim, record)
        return (best[1], best[0]) if best else None

    def count_memories(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM memories").fetchone()
        return int(row["c"])

    # --------------------------------------------------------------- projects
    def create_project(self, record: ProjectRecord) -> ProjectRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        with self._lock:
            self._conn.execute(
                """INSERT INTO projects (id, user_id, name, description, status, metadata, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.id,
                    record.user_id,
                    record.name,
                    record.description,
                    record.status,
                    self._dump_meta(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()
        return record

    def get_project(self, project_id: str) -> ProjectRecord | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return self._project_from_row(row) if row else None

    def find_project_by_name(self, name: str) -> ProjectRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM projects WHERE lower(name)=lower(?) ORDER BY created_at LIMIT 1",
                (name,),
            ).fetchone()
        return self._project_from_row(row) if row else None

    def list_projects(self, limit: int = 100) -> list[ProjectRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._project_from_row(r) for r in rows]

    def count_projects(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()
        return int(row["c"])

    # --------------------------------------------------------------- documents
    def _document_from_row(self, row: sqlite3.Row) -> DocumentRecord:
        return DocumentRecord(
            id=row["id"],
            user_id=row["user_id"],
            project_id=row["project_id"],
            filename=row["filename"],
            title=row["title"],
            source=row["source"],
            mime_type=row["mime_type"],
            metadata=self._load_meta(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        with self._lock:
            self._conn.execute(
                """INSERT INTO documents
                   (id, user_id, project_id, filename, title, source, mime_type,
                    metadata, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.id,
                    record.user_id,
                    record.project_id,
                    record.filename,
                    record.title,
                    record.source,
                    record.mime_type,
                    self._dump_meta(record.metadata),
                    record.created_at,
                    record.updated_at,
                ),
            )
            self._conn.commit()
        return record

    def get_document(self, document_id: str) -> DocumentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM documents WHERE id=?", (document_id,)
            ).fetchone()
        return self._document_from_row(row) if row else None

    def list_documents(
        self,
        limit: int = 50,
        project_id: str | None = None,
    ) -> list[DocumentRecord]:
        sql = "SELECT * FROM documents"
        values: list = []
        if project_id:
            sql += " WHERE project_id=?"
            values.append(project_id)
        sql += " ORDER BY created_at DESC LIMIT ?"
        values.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        return [self._document_from_row(r) for r in rows]

    def delete_document(self, document_id: str) -> dict:
        memory_ids: list[str] = []
        chunks_removed = 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT metadata FROM document_chunks WHERE document_id=?", (document_id,)
            ).fetchall()
            for row in rows:
                meta = self._load_meta(row["metadata"])
                mid = meta.get("memory_id")
                if mid:
                    memory_ids.append(str(mid))
            cur = self._conn.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            chunks_removed = cur.rowcount
            memories_removed = 0
            for mid in memory_ids:
                mcur = self._conn.execute("DELETE FROM memories WHERE id=?", (mid,))
                memories_removed += max(mcur.rowcount, 0)
            dcur = self._conn.execute("DELETE FROM documents WHERE id=?", (document_id,))
            if dcur.rowcount == 0 and chunks_removed == 0:
                self._conn.commit()
                return {"chunks_removed": 0, "memories_removed": 0}
            self._conn.commit()
        return {"chunks_removed": chunks_removed, "memories_removed": memories_removed}

    def create_document_chunk(self, record: DocumentChunkRecord) -> DocumentChunkRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        with self._lock:
            self._conn.execute(
                """INSERT INTO document_chunks
                   (id, document_id, chunk_index, content, token_count, metadata,
                    embedding, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    record.id,
                    record.document_id,
                    int(record.chunk_index),
                    record.content,
                    record.token_count,
                    self._dump_meta(record.metadata),
                    self._dump_embedding(record.embedding),
                    record.created_at,
                ),
            )
            self._conn.commit()
        return record

    def list_document_chunks(self, document_id: str, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, chunk_index, content, token_count, metadata FROM document_chunks "
                "WHERE document_id=? ORDER BY chunk_index ASC LIMIT ?",
                (document_id, max(1, min(int(limit), 2000))),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "token_count": r["token_count"],
                "metadata": self._load_meta(r["metadata"]),
            }
            for r in rows
        ]

    def count_documents(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()
        return int(row["c"])

    def count_document_chunks(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS c FROM document_chunks").fetchone()
        return int(row["c"])

    # ------------------------------------------------------------------- audit
    _AUDIT_COLUMNS = (
        "ts", "kind", "request_id", "api_key_hint", "method",
        "path", "status", "duration_ms", "result_count", "detail",
    )

    def record_audit(self, event: dict) -> None:
        row = {key: event.get(key) for key in self._AUDIT_COLUMNS}
        if not isinstance(row.get("detail"), str):
            import json as _json

            row["detail"] = _json.dumps(row.get("detail") or {}, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                f"INSERT INTO audit_events ({', '.join(self._AUDIT_COLUMNS)}) "
                f"VALUES ({', '.join('?' for _ in self._AUDIT_COLUMNS)})",
                tuple(row[c] for c in self._AUDIT_COLUMNS),
            )
            self._conn.commit()

    def list_audit(self, limit: int = 50) -> list[dict]:
        import json as _json

        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        events = []
        for r in rows:
            item = dict(r)
            try:
                item["detail"] = _json.loads(item.get("detail") or "{}")
            except _json.JSONDecodeError:
                item["detail"] = {}
            events.append(item)
        return events
