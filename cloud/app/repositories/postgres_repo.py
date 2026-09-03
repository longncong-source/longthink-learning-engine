"""PostgreSQL + pgvector backend (MVP production target).

Notes:
  - embedding column is declared as untyped `vector` so EMBEDDING_DIMENSION stays
    configurable (spec section 7). Exact-NN via `<=>` operator (sequential scan);
    add HNSW/IVFFlat indexes once a fixed dimension is chosen in production.
  - candidate selection uses vector distance; final hybrid scoring is computed
    with the same pure functions as the SQLite backend (consistency across backends).
"""

from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path

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
    isoformat_now,
    keyword_score,
    recency_score,
)

_MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

_UPDATABLE_COLUMNS = {
    "type",
    "title",
    "content",
    "summary",
    "source",
    "importance",
    "confidence",
}


def _now() -> str:
    return isoformat_now()


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.9g}" for x in vector) + "]"


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def _meta_out(raw) -> dict:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


class PostgresRepository(BaseRepository):
    backend_name = "postgres+pgvector"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool = None
        self._pool_ready = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ pool
    def _get_pool(self):
        with self._lock:
            if self._pool is None:
                try:
                    from psycopg_pool import ConnectionPool
                    from psycopg.rows import dict_row
                except ImportError as exc:  # pragma: no cover
                    raise RepositoryError(
                        "psycopg is not installed. Run: pip install -r cloud/requirements-postgres.txt"
                    ) from exc
                # psycopg_pool >= 3.2 no longer auto-opens pools on construction.
                self._pool = ConnectionPool(
                    self.database_url,
                    min_size=1,
                    max_size=4,
                    open=False,
                    kwargs={"row_factory": dict_row, "connect_timeout": 5},
                )
                self._pool_ready = False
            if not self._pool_ready:
                try:
                    self._pool.open(wait=True, timeout=10)
                except Exception as exc:
                    raise RepositoryError(f"PostgreSQL pool failed to open: {exc}") from exc
                self._pool_ready = True
            return self._pool

    def _connection(self):
        pool = self._get_pool()
        try:
            return pool.connection(timeout=8)
        except Exception as exc:  # noqa: BLE001 - pool/connection failures -> RepositoryError
            raise RepositoryError(f"PostgreSQL connection failed: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None
            self._pool_ready = False

    # ------------------------------------------------------------- lifecycle
    def init_schema(self) -> None:
        sql = "\n".join(p.read_text(encoding="utf-8") for p in sorted(_MIGRATIONS.glob("*.sql")))
        try:
            with self._connection() as conn:
                conn.execute(sql)
                conn.commit()
        except RepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Schema initialisation failed: {exc}") from exc

    def ping(self) -> bool:
        try:
            with self._connection() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:  # noqa: BLE001
            return False

    def backend_info(self) -> dict:
        info: dict = {"backend": self.backend_name}
        try:
            with self._connection() as conn:
                row = conn.execute(
                    "SELECT version() AS v, extname FROM pg_extension WHERE extname='vector'"
                ).fetchone()
                info["server"] = (row or {}).get("v", "").split(",")[0] if row else "unknown"
                info["pgvector"] = bool(row and row.get("extname") == "vector")
        except Exception as exc:  # noqa: BLE001
            info["error"] = str(exc)
        return info

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _memory_from_row(row: dict) -> MemoryRecord:
        embedding = row.get("embedding")
        if embedding is not None and not isinstance(embedding, list):
            # pgvector returns a string like "[0.1,0.2]" when no adapter registered
            try:
                embedding = [float(x) for x in str(embedding).strip("[]").split(",") if x != ""]
            except ValueError:
                embedding = None
        return MemoryRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            project_id=str(row["project_id"]) if row.get("project_id") else None,
            type=row["type"],
            title=row["title"],
            content=row["content"],
            summary=row.get("summary"),
            source=row.get("source"),
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            metadata=_meta_out(row.get("metadata")),
            created_at=_iso(row.get("created_at")),
            updated_at=_iso(row.get("updated_at")),
            embedding=embedding,
        )

    @staticmethod
    def _project_from_row(row: dict) -> ProjectRecord:
        return ProjectRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            name=row["name"],
            description=row.get("description"),
            status=row.get("status", "active"),
            metadata=_meta_out(row.get("metadata")),
            created_at=_iso(row.get("created_at")),
            updated_at=_iso(row.get("updated_at")),
        )

    def _fetchone(self, sql: str, params: dict) -> dict | None:
        with self._connection() as conn:
            return conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: dict) -> list[dict]:
        with self._connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    # --------------------------------------------------------------- memories
    def create_memory(self, record: MemoryRecord) -> MemoryRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        sql = """
            INSERT INTO memories
                (id, user_id, project_id, type, title, content, summary, source,
                 importance, confidence, metadata, embedding, created_at, updated_at)
            VALUES (%(id)s::uuid, %(user_id)s::uuid, %(project_id)s::uuid, %(type)s,
                    %(title)s, %(content)s, %(summary)s, %(source)s,
                    %(importance)s, %(confidence)s, %(metadata)s::jsonb,
                    %(embedding)s::vector, %(created_at)s, %(updated_at)s)
            RETURNING *
        """
        params = {
            "id": record.id,
            "user_id": record.user_id,
            "project_id": record.project_id,
            "type": record.type,
            "title": record.title,
            "content": record.content,
            "summary": record.summary,
            "source": record.source,
            "importance": float(record.importance),
            "confidence": float(record.confidence),
            "metadata": json.dumps(record.metadata or {}, ensure_ascii=False),
            "embedding": _vector_literal(record.embedding) if record.embedding else None,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }
        try:
            row = self._fetchone(sql, params)
        except RepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Memory insert failed: {exc}") from exc
        return self._memory_from_row(row)

    def get_memory(self, memory_id: str) -> MemoryRecord | None:
        row = self._fetchone("SELECT * FROM memories WHERE id=%(id)s::uuid", {"id": memory_id})
        return self._memory_from_row(row) if row else None

    def delete_memory(self, memory_id: str) -> bool:
        row = self._fetchone(
            "DELETE FROM memories WHERE id=%(id)s::uuid RETURNING id", {"id": memory_id}
        )
        return row is not None

    def update_memory(self, memory_id: str, fields: dict) -> MemoryRecord:
        clean = {k: v for k, v in fields.items() if k in _UPDATABLE_COLUMNS}
        sets = [f"{k} = %({k})s" for k in clean]
        params: dict = {k: v for k, v in clean.items()}
        params["id"] = memory_id
        if "embedding" in fields:
            vector = fields["embedding"]
            sets.append("embedding = %(embedding)s::vector")
            params["embedding"] = _vector_literal(vector) if vector else None
        if "metadata" in fields:
            sets.append("metadata = %(metadata_merge)s::jsonb")
            params["metadata_merge"] = json.dumps(fields["metadata"], ensure_ascii=False)
        sets.append("updated_at = now()")
        if not sets:
            existing = self.get_memory(memory_id)
            if existing is None:
                raise RepositoryError(f"Memory {memory_id} not found for update")
            return existing
        sql = f"UPDATE memories SET {', '.join(sets)} WHERE id=%(id)s::uuid RETURNING *"
        try:
            row = self._fetchone(sql, params)
        except RepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Memory update failed: {exc}") from exc
        if row is None:
            raise RepositoryError(f"Memory {memory_id} not found for update")
        return self._memory_from_row(row)

    def list_memories(
        self,
        limit: int = 50,
        offset: int = 0,
        project_id: str | None = None,
        memory_type: str | None = None,
    ) -> list[MemoryRecord]:
        sql = "SELECT * FROM memories WHERE (%(project_id)s::uuid IS NULL OR project_id=%(project_id)s::uuid)"
        params: dict = {"project_id": project_id}
        if memory_type:
            sql += " AND type = %(type)s"
            params["type"] = memory_type
        sql += " ORDER BY updated_at DESC LIMIT %(limit)s OFFSET %(offset)s"
        params.update({"limit": int(limit), "offset": int(offset)})
        rows = self._fetchall(sql, params)
        return [self._memory_from_row(r) for r in rows]

    def search(
        self,
        params: SearchParams,
        weights: dict[str, float],
        half_life_days: float,
        candidate_limit: int,
    ) -> list[ScoredMemory]:
        emb_literal = _vector_literal(params.query_embedding)
        sql = """
            SELECT m.*,
                   CASE WHEN m.embedding IS NULL THEN 0.0
                        ELSE GREATEST(0.0, LEAST(1.0, 1.0 - (m.embedding <=> %(emb)s::vector)))
                   END AS semantic_score
            FROM memories m
            WHERE m.importance >= %(min_importance)s
              AND (%(project_id)s::uuid IS NULL OR m.project_id = %(project_id)s::uuid)
              AND (%(types)s::text[] IS NULL OR m.type = ANY(%(types)s::text[]))
              AND (%(metadata)s::jsonb IS NULL OR m.metadata @> %(metadata)s::jsonb)
            ORDER BY semantic_score DESC, m.updated_at DESC
            LIMIT %(candidate_limit)s
        """
        sql_params = {
            "emb": emb_literal,
            "min_importance": float(params.min_importance),
            "project_id": params.project_id,
            "types": params.types,
            "metadata": (
                json.dumps(params.metadata_filter, ensure_ascii=False) if params.metadata_filter else None
            ),
            "candidate_limit": int(candidate_limit),
        }
        try:
            rows = self._fetchall(sql, sql_params)
        except RepositoryError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise RepositoryError(f"Search query failed: {exc}") from exc

        scored: list[ScoredMemory] = []
        for row in rows:
            record = self._memory_from_row(row)
            semantic = float(row.get("semantic_score") or 0.0)
            document = " ".join(filter(None, [record.title, record.summary, record.content]))
            keyword = keyword_score(params.query, document)
            recency = recency_score(record.updated_at or record.created_at or _now(), half_life_days)
            total = combine_scores(semantic, keyword, record.importance, recency, weights)
            scored.append(ScoredMemory(record, semantic, keyword, record.importance, recency, total))
        scored.sort(key=lambda s: (s.total, s.record.updated_at or ""), reverse=True)
        return scored[: params.top_k]

    def nearest_neighbor(
        self,
        embedding: list[float],
        project_id: str | None,
        memory_type: str,
    ) -> tuple[MemoryRecord, float] | None:
        sql = """
            SELECT *, 1 - (embedding <=> %(emb)s::vector) AS similarity
            FROM memories
            WHERE embedding IS NOT NULL
              AND type = %(type)s
              AND (%(project_id)s::uuid IS NULL OR project_id = %(project_id)s::uuid)
            ORDER BY embedding <=> %(emb)s::vector
            LIMIT 1
        """
        row = self._fetchone(
            sql,
            {"emb": _vector_literal(embedding), "type": memory_type, "project_id": project_id},
        )
        if row is None:
            return None
        return self._memory_from_row(row), float(row.get("similarity") or 0.0)

    def count_memories(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS c FROM memories", {})
        return int((row or {}).get("c") or 0)

    # --------------------------------------------------------------- projects
    def create_project(self, record: ProjectRecord) -> ProjectRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        row = self._fetchone(
            """
            INSERT INTO projects (id, user_id, name, description, status, metadata, created_at, updated_at)
            VALUES (%(id)s::uuid, %(user_id)s::uuid, %(name)s, %(description)s, %(status)s,
                    %(metadata)s::jsonb, %(created_at)s, %(updated_at)s)
            RETURNING *
            """,
            {
                "id": record.id,
                "user_id": record.user_id,
                "name": record.name,
                "description": record.description,
                "status": record.status,
                "metadata": json.dumps(record.metadata or {}, ensure_ascii=False),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
        )
        return self._project_from_row(row)

    def get_project(self, project_id: str) -> ProjectRecord | None:
        row = self._fetchone("SELECT * FROM projects WHERE id=%(id)s::uuid", {"id": project_id})
        return self._project_from_row(row) if row else None

    def find_project_by_name(self, name: str) -> ProjectRecord | None:
        row = self._fetchone(
            "SELECT * FROM projects WHERE lower(name)=lower(%(name)s) ORDER BY created_at LIMIT 1",
            {"name": name},
        )
        return self._project_from_row(row) if row else None

    def list_projects(self, limit: int = 100) -> list[ProjectRecord]:
        rows = self._fetchall(
            "SELECT * FROM projects ORDER BY created_at DESC LIMIT %(limit)s", {"limit": int(limit)}
        )
        return [self._project_from_row(r) for r in rows]

    def count_projects(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS c FROM projects", {})
        return int((row or {}).get("c") or 0)

    # --------------------------------------------------------------- documents
    @staticmethod
    def _document_from_row(row: dict) -> DocumentRecord:
        return DocumentRecord(
            id=str(row["id"]),
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            project_id=str(row["project_id"]) if row.get("project_id") else None,
            filename=row["filename"],
            title=row.get("title"),
            source=row.get("source"),
            mime_type=row.get("mime_type"),
            metadata=_meta_out(row.get("metadata")),
            created_at=_iso(row.get("created_at")),
            updated_at=_iso(row.get("updated_at")),
        )

    def create_document(self, record: DocumentRecord) -> DocumentRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        record.updated_at = record.updated_at or record.created_at
        row = self._fetchone(
            """
            INSERT INTO documents
                (id, user_id, project_id, filename, title, source, mime_type,
                 metadata, created_at, updated_at)
            VALUES (%(id)s::uuid, %(user_id)s::uuid, %(project_id)s::uuid, %(filename)s,
                    %(title)s, %(source)s, %(mime_type)s, %(metadata)s::jsonb,
                    %(created_at)s, %(updated_at)s)
            RETURNING *
            """,
            {
                "id": record.id,
                "user_id": record.user_id,
                "project_id": record.project_id,
                "filename": record.filename,
                "title": record.title,
                "source": record.source,
                "mime_type": record.mime_type,
                "metadata": json.dumps(record.metadata or {}, ensure_ascii=False),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
        )
        return self._document_from_row(row)

    def get_document(self, document_id: str) -> DocumentRecord | None:
        row = self._fetchone("SELECT * FROM documents WHERE id=%(id)s::uuid", {"id": document_id})
        return self._document_from_row(row) if row else None

    def list_documents(
        self, limit: int = 50, project_id: str | None = None, query: str | None = None
    ) -> list[DocumentRecord]:
        rows = self._fetchall(
            """
            SELECT * FROM documents
            WHERE (%(project_id)s::uuid IS NULL OR project_id=%(project_id)s::uuid)
              AND (%(q)s::text IS NULL OR filename ILIKE %(like)s OR COALESCE(title,'') ILIKE %(like)s
                   OR COALESCE(source,'') ILIKE %(like)s)
            ORDER BY created_at DESC LIMIT %(limit)s
            """,
            {
                "limit": int(limit),
                "project_id": project_id,
                "q": query or None,
                "like": f"%{query}%" if query else None,
            },
        )
        return [self._document_from_row(r) for r in rows]

    def delete_document(self, document_id: str) -> dict:
        rows = self._fetchall(
            "SELECT metadata->>'memory_id' AS mid FROM document_chunks "
            "WHERE document_id=%(d)s::uuid AND metadata ? 'memory_id'",
            {"d": document_id},
        )
        memory_ids = [r["mid"] for r in rows if r.get("mid")]
        with self._connection() as conn:
            memories_removed = 0
            if memory_ids:
                mcur = conn.execute(
                    "DELETE FROM memories WHERE id = ANY(%(mids)s::uuid[])",
                    {"mids": memory_ids},
                )
                memories_removed = mcur.rowcount
            ccur = conn.execute(
                "DELETE FROM document_chunks WHERE document_id=%(d)s::uuid", {"d": document_id}
            )
            chunks_removed = ccur.rowcount
            dcur = conn.execute(
                "DELETE FROM documents WHERE id=%(d)s::uuid", {"d": document_id}
            )
            if dcur.rowcount == 0 and chunks_removed == 0 and memories_removed == 0:
                conn.commit()
                return {"chunks_removed": 0, "memories_removed": 0}
            conn.commit()
        return {"chunks_removed": chunks_removed, "memories_removed": memories_removed}

    def create_document_chunk(self, record: DocumentChunkRecord) -> DocumentChunkRecord:
        record.id = record.id or str(uuid.uuid4())
        record.created_at = record.created_at or _now()
        row = self._fetchone(
            """
            INSERT INTO document_chunks
                (id, document_id, chunk_index, content, token_count, metadata,
                 embedding, created_at)
            VALUES (%(id)s::uuid, %(document_id)s::uuid, %(chunk_index)s, %(content)s,
                    %(token_count)s, %(metadata)s::jsonb, %(embedding)s::vector, %(created_at)s)
            RETURNING *
            """,
            {
                "id": record.id,
                "document_id": record.document_id,
                "chunk_index": int(record.chunk_index),
                "content": record.content,
                "token_count": record.token_count,
                "metadata": json.dumps(record.metadata or {}, ensure_ascii=False),
                "embedding": _vector_literal(record.embedding) if record.embedding else None,
                "created_at": record.created_at,
            },
        )
        record.id = str(row["id"])
        return record

    def list_document_chunks(self, document_id: str, limit: int = 500) -> list[dict]:
        rows = self._fetchall(
            "SELECT id, chunk_index, content, token_count, metadata FROM document_chunks "
            "WHERE document_id=%(d)s::uuid ORDER BY chunk_index ASC LIMIT %(limit)s",
            {"d": document_id, "limit": max(1, min(int(limit), 2000))},
        )
        out = []
        for r in rows:
            meta = r.get("metadata") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            out.append(
                {
                    "id": str(r.get("id")),
                    "chunk_index": r.get("chunk_index"),
                    "content": r.get("content"),
                    "token_count": r.get("token_count"),
                    "metadata": meta,
                }
            )
        return out

    def count_documents(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS c FROM documents", {})
        return int((row or {}).get("c") or 0)

    def count_document_chunks(self) -> int:
        row = self._fetchone("SELECT COUNT(*) AS c FROM document_chunks", {})
        return int((row or {}).get("c") or 0)

    # ------------------------------------------------------------------- audit
    def record_audit(self, event: dict) -> None:
        detail = event.get("detail")
        if not isinstance(detail, str):
            detail = json.dumps(detail or {}, ensure_ascii=False)
        self._fetchone(
            """
            INSERT INTO audit_events
                (ts, kind, request_id, api_key_hint, method, path,
                 status, duration_ms, result_count, detail)
            VALUES (%(ts)s, %(kind)s, %(request_id)s, %(api_key_hint)s, %(method)s,
                    %(path)s, %(status)s, %(duration_ms)s, %(result_count)s, %(detail)s::jsonb)
            RETURNING id
            """,
            {
                "ts": event.get("ts"),
                "kind": event.get("kind"),
                "request_id": event.get("request_id"),
                "api_key_hint": event.get("api_key_hint"),
                "method": event.get("method"),
                "path": event.get("path"),
                "status": event.get("status"),
                "duration_ms": event.get("duration_ms"),
                "result_count": event.get("result_count"),
                "detail": detail,
            },
        )

    def list_audit(self, limit: int = 50) -> list[dict]:
        rows = self._fetchall(
            "SELECT * FROM audit_events ORDER BY id DESC LIMIT %(limit)s",
            {"limit": int(limit)},
        )
        events = []
        for row in rows:
            item = dict(row)
            if hasattr(item.get("ts"), "isoformat"):
                item["ts"] = item["ts"].isoformat()
            item["id"] = str(item.get("id"))
            events.append(item)
        return events
