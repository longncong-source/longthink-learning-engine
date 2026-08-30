"""Mid Brain Memory Manager - Independent memory architecture for Mid Brain."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class MemoryItem:
    """A single memory item in Mid Brain."""
    id: str
    content: str
    question: str | None = None
    memory_type: str = "semantic"  # working, episodic, semantic, procedural, strategic, meta
    project_id: str | None = None
    confidence: float = 0.5
    importance: float = 0.5
    source: str = "mid-brain"
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    version: int = 1


@dataclass(slots=True)
class MemoryQuery:
    """Query parameters for memory retrieval."""
    query: str
    project_id: str | None = None
    memory_types: list[str] | None = None
    min_confidence: float = 0.0
    min_importance: float = 0.0
    limit: int = 10
    offset: int = 0


@dataclass(slots=True)
class MemoryResult:
    """Result of memory retrieval."""
    items: list[MemoryItem]
    total: int
    query: str


class MemoryManager:
    """
    Mid Brain Memory Manager.

    Memory Types:
    - Working Memory: Temporary, short-term context
    - Episodic Memory: Specific events, experiences
    - Semantic Memory: General knowledge, facts
    - Procedural Memory: How-to knowledge, strategies
    - Strategic Memory: High-level strategies, decision patterns
    - Meta Memory: Knowledge about knowledge (confidence, reliability)
    """

    VALID_TYPES = {"working", "episodic", "semantic", "procedural", "strategic", "meta"}

    def __init__(self, db_path: str = "mid_brain_data/memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._initialized = False

    def initialize(self) -> None:
        """Initialize database schema."""
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    question TEXT,
                    memory_type TEXT NOT NULL DEFAULT 'semantic',
                    project_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    importance REAL NOT NULL DEFAULT 0.5,
                    source TEXT NOT NULL DEFAULT 'mid-brain',
                    trace_id TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
                CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
                CREATE INDEX IF NOT EXISTS idx_memories_trace ON memories(trace_id);
                CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);

                CREATE TABLE IF NOT EXISTS memory_embeddings (
                    memory_id TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, link_type),
                    FOREIGN KEY (source_id) REFERENCES memories(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES memories(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_links_source ON memory_links(source_id);
                CREATE INDEX IF NOT EXISTS idx_links_target ON memory_links(target_id);
            """)
            self._conn.commit()
        self._initialized = True

    def store(
        self,
        content: str,
        question: str | None = None,
        memory_type: str = "semantic",
        project_id: str | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
        source: str = "mid-brain",
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Store a new memory item."""
        if not self._initialized:
            self.initialize()

        if memory_type not in self.VALID_TYPES:
            memory_type = "semantic"

        memory_id = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        item = MemoryItem(
            id=memory_id,
            content=content,
            question=question,
            memory_type=memory_type,
            project_id=project_id,
            confidence=confidence,
            importance=importance,
            source=source,
            trace_id=trace_id,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._conn.execute(
                """INSERT INTO memories
                   (id, content, question, memory_type, project_id, confidence,
                    importance, source, trace_id, metadata, created_at, updated_at, version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item.id,
                    item.content,
                    item.question,
                    item.memory_type,
                    item.project_id,
                    item.confidence,
                    item.importance,
                    item.source,
                    item.trace_id,
                    json.dumps(item.metadata, ensure_ascii=False),
                    item.created_at,
                    item.updated_at,
                    item.version,
                ),
            )
            self._conn.commit()

        return {"stored": True, "memory_id": memory_id, "item": item}

    def retrieve(self, query: MemoryQuery | str, **kwargs) -> dict[str, Any]:
        """Retrieve memories matching query."""
        if not self._initialized:
            self.initialize()

        if isinstance(query, str):
            query = MemoryQuery(query=query, **kwargs)

        # Simple keyword search for now (will be enhanced with embeddings)
        sql = "SELECT * FROM memories WHERE 1=1"
        values = []

        if query.project_id:
            sql += " AND project_id = ?"
            values.append(query.project_id)

        if query.memory_types:
            placeholders = ",".join("?" for _ in query.memory_types)
            sql += f" AND memory_type IN ({placeholders})"
            values.extend(query.memory_types)

        if query.min_confidence > 0:
            sql += " AND confidence >= ?"
            values.append(query.min_confidence)

        if query.min_importance > 0:
            sql += " AND importance >= ?"
            values.append(query.min_importance)

        # Simple text search
        if query.query:
            sql += " AND (content LIKE ? OR question LIKE ?)"
            like_term = f"%{query.query}%"
            values.extend([like_term, like_term])

        sql += " ORDER BY importance DESC, confidence DESC, created_at DESC LIMIT ? OFFSET ?"
        values.extend([query.limit, query.offset])

        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()

        items = [self._row_to_item(r) for r in rows]

        # Count total
        count_sql = sql.replace("SELECT *", "SELECT COUNT(*) as c").split("ORDER BY")[0]
        with self._lock:
            count_row = self._conn.execute(count_sql, values[:-2]).fetchone()
        total = count_row["c"] if count_row else 0

        return {
            "results": [self._item_to_dict(item) for item in items],
            "total": total,
            "query": query.query,
        }

    def get(self, memory_id: str) -> MemoryItem | None:
        """Get a single memory by ID."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def update(self, memory_id: str, fields: dict[str, Any]) -> MemoryItem | None:
        """Update a memory item."""
        if not self._initialized:
            self.initialize()

        allowed = {"content", "confidence", "importance", "metadata", "memory_type", "project_id"}
        clean = {k: v for k, v in fields.items() if k in allowed}
        if not clean:
            return self.get(memory_id)

        clean["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        clean["version"] = "version + 1"

        sets = []
        values = []
        for key, value in clean.items():
            if key == "version":
                sets.append("version = version + 1")
            elif key == "metadata":
                sets.append("metadata = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                sets.append(f"{key} = ?")
                values.append(value)

        values.append(memory_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE memories SET {', '.join(sets)} WHERE id=?",
                values,
            )
            self._conn.commit()

        return self.get(memory_id)

    def delete(self, memory_id: str) -> bool:
        """Delete a memory item."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
            self._conn.commit()
        return cur.rowcount > 0

    def link(self, source_id: str, target_id: str, link_type: str, weight: float = 1.0) -> bool:
        """Create a link between two memories."""
        if not self._initialized:
            self.initialize()

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            try:
                self._conn.execute(
                    """INSERT OR REPLACE INTO memory_links
                       (source_id, target_id, link_type, weight, created_at)
                       VALUES (?,?,?,?,?)""",
                    (source_id, target_id, link_type, weight, now),
                )
                self._conn.commit()
                return True
            except sqlite3.Error:
                return False

    def get_links(self, memory_id: str) -> list[dict[str, Any]]:
        """Get all links for a memory."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM memory_links WHERE source_id=? OR target_id=?",
                (memory_id, memory_id),
            ).fetchall()
        return [dict(r) for r in rows]

    def promote(self, memory_id: str, new_type: str) -> MemoryItem | None:
        """Promote memory to a different type (e.g., working -> semantic)."""
        if new_type not in self.VALID_TYPES:
            return None
        return self.update(memory_id, {"memory_type": new_type})

    def archive(self, memory_id: str) -> bool:
        """Archive a memory (mark as low importance)."""
        return self.update(memory_id, {"importance": 0.1}) is not None

    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
            by_type = {}
            for mtype in self.VALID_TYPES:
                count = self._conn.execute(
                    "SELECT COUNT(*) as c FROM memories WHERE memory_type=?",
                    (mtype,),
                ).fetchone()["c"]
                by_type[mtype] = count

        return {
            "total_memories": total,
            "by_type": by_type,
        }

    # ------------------------------------------------------------------ helpers

    def _row_to_item(self, row: sqlite3.Row) -> MemoryItem:
        return MemoryItem(
            id=row["id"],
            content=row["content"],
            question=row["question"],
            memory_type=row["memory_type"],
            project_id=row["project_id"],
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            source=row["source"],
            trace_id=row["trace_id"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            version=int(row["version"]),
        )

    def _item_to_dict(self, item: MemoryItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "content": item.content,
            "question": item.question,
            "type": item.memory_type,
            "project_id": item.project_id,
            "confidence": item.confidence,
            "importance": item.importance,
            "source": item.source,
            "trace_id": item.trace_id,
            "metadata": item.metadata,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "version": item.version,
        }

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._conn.close()
