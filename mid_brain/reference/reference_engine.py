"""Mid Brain Reference Engine - Future reference retrieval for similar problems."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


@dataclass(slots=True)
class ReferenceItem:
    """A reference item for future retrieval."""
    id: str
    question: str
    answer: str
    confidence: float
    trace_id: str
    project_id: str | None
    tags: list[str] = field(default_factory=list)
    success: bool = True
    used_count: int = 0
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    last_used_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ReferenceQuery:
    """Query for finding similar references."""
    question: str
    project_id: str | None = None
    min_confidence: float = 0.0
    limit: int = 5


@dataclass(slots=True)
class ReferenceResult:
    """Result of reference retrieval."""
    items: list[ReferenceItem]
    total: int
    query: str


class ReferenceEngine:
    """
    Future Reference Engine.

    When a new question arrives:
    1. Search previous questions
    2. Search previous answers
    3. Search similar problems
    4. Search decisions
    5. Search experiences
    6. Search lessons
    7. Search strategies
    8. Search previous failures
    9. Search successful approaches

    Goal: DO NOT SOLVE THE SAME PROBLEM FROM ZERO.
    """

    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/reference.db") -> None:
        self.mid_brain = mid_brain
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = None  # Will be set in initialize
        self._initialized = False

    def initialize(self) -> None:
        """Initialize database schema."""
        import threading
        self._lock = threading.RLock()

        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS reference_items (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    trace_id TEXT,
                    project_id TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    success INTEGER NOT NULL DEFAULT 1,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_ref_question ON reference_items(question);
                CREATE INDEX IF NOT EXISTS idx_ref_project ON reference_items(project_id);
                CREATE INDEX IF NOT EXISTS idx_ref_confidence ON reference_items(confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_ref_created ON reference_items(created_at DESC);
            """)
            self._conn.commit()
        self._initialized = True

    def index(
        self,
        question: str,
        answer: str,
        confidence: float,
        trace_id: str,
        project_id: str | None = None,
        tags: list[str] | None = None,
        success: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Index a Q&A pair for future reference."""
        if not self._initialized:
            self.initialize()

        ref_id = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        import json
        with self._lock:
            self._conn.execute(
                """INSERT INTO reference_items
                   (id, question, answer, confidence, trace_id, project_id,
                    tags, success, used_count, created_at, metadata)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ref_id,
                    question,
                    answer,
                    confidence,
                    trace_id,
                    project_id,
                    json.dumps(tags or [], ensure_ascii=False),
                    1 if success else 0,
                    0,
                    now,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()

        return {"indexed": True, "reference_id": ref_id}

    def retrieve(
        self,
        query: ReferenceQuery | str,
        **kwargs,
    ) -> dict[str, Any]:
        """Retrieve relevant references for a question."""
        if not self._initialized:
            self.initialize()

        if isinstance(query, str):
            query = ReferenceQuery(question=query, **kwargs)

        sql = "SELECT * FROM reference_items WHERE 1=1"
        values = []

        if query.project_id:
            sql += " AND project_id = ?"
            values.append(query.project_id)

        if query.min_confidence > 0:
            sql += " AND confidence >= ?"
            values.append(query.min_confidence)

        # Simple keyword search
        if query.question:
            keywords = query.question.lower().split()
            conditions = []
            for kw in keywords[:5]:  # Limit keywords
                conditions.append("question LIKE ?")
                values.append(f"%{kw}%")
            if conditions:
                sql += " AND (" + " OR ".join(conditions) + ")"

        sql += " ORDER BY confidence DESC, used_count DESC, created_at DESC LIMIT ?"
        values.append(query.limit)

        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()

        items = [self._row_to_item(r) for r in rows]

        # Update used_count for retrieved items
        for item in items:
            self._increment_used(item.id)

        return asdict(ReferenceResult(
            items=items,
            total=len(items),
            query=query.question,
        ))

    def _increment_used(self, ref_id: str) -> None:
        """Increment used_count and update last_used_at."""
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            self._conn.execute(
                "UPDATE reference_items SET used_count = used_count + 1, last_used_at = ? WHERE id = ?",
                (now, ref_id),
            )
            self._conn.commit()

    def find_similar_experience(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        """Find similar past experiences."""
        return self.retrieve(ReferenceQuery(question=question, project_id=project_id, limit=limit))["items"]

    def find_similar_decision(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        """Find similar past decisions."""
        # Filter by tags containing 'decision' - simplified
        return self.retrieve(ReferenceQuery(question=question, project_id=project_id, limit=limit))["items"]

    def find_relevant_lesson(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        """Find relevant lessons learned."""
        return self.retrieve(ReferenceQuery(question=question, project_id=project_id, limit=limit))["items"]

    def find_relevant_strategy(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        """Find relevant strategies."""
        return self.retrieve(ReferenceQuery(question=question, project_id=project_id, limit=limit))["items"]

    def find_previous_failure(self, question: str, project_id: str | None = None, limit: int = 3) -> list[dict[str, Any]]:
        """Find previous failures for similar problems."""
        if not self._initialized:
            self.initialize()

        sql = "SELECT * FROM reference_items WHERE success = 0"
        values = []
        if project_id:
            sql += " AND project_id = ?"
            values.append(project_id)
        # Add keyword search
        if question:
            keywords = question.lower().split()
            conditions = []
            for kw in keywords[:3]:
                conditions.append("question LIKE ?")
                values.append(f"%{kw}%")
            if conditions:
                sql += " AND (" + " OR ".join(conditions) + ")"
        sql += " ORDER BY created_at DESC LIMIT ?"
        values.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()
        return [dict(r) for r in rows]

    def _row_to_item(self, row) -> ReferenceItem:
        import json
        return ReferenceItem(
            id=row["id"],
            question=row["question"],
            answer=row["answer"],
            confidence=float(row["confidence"]),
            trace_id=row["trace_id"],
            project_id=row["project_id"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            success=bool(row["success"]),
            used_count=int(row["used_count"]),
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def close(self) -> None:
        """Close database connection."""
        if self._lock:
            with self._lock:
                self._conn.close()
