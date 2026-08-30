"""Mid Brain Learning Engine - Extract and store learning from experience."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


class LearningType:
    EXPERIENCE = "experience"
    DECISION = "decision"
    LESSON = "lesson"
    STRATEGY = "strategy"
    FAILURE = "failure"
    SUCCESS = "success"


@dataclass(slots=True)
class LearningItem:
    """A learned item from reflection."""
    id: str
    learning_type: str
    content: str
    source_question: str
    source_answer: str
    confidence: float
    trace_id: str
    project_id: str | None
    importance: float = 0.5
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LearningResult:
    """Result of learning extraction."""
    stored_count: int
    items: list[LearningItem]


class LearningEngine:
    """
    Learning Engine for Mid Brain.

    Learning lifecycle:
    OBSERVE → ANALYZE → REFLECT → LEARN → STORE → REUSE

    Extracts from reflection:
    - Experience (what happened)
    - Decision (what was decided)
    - Lesson (what was learned)
    - Strategy (what approach worked)
    - Failure (what didn't work)
    - Success (what worked well)
    """

    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/learning.db") -> None:
        self.mid_brain = mid_brain
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = None
        self._initialized = False

    def initialize(self) -> None:
        """Initialize database schema."""
        import threading
        self._lock = threading.RLock()

        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS learning (
                    id TEXT PRIMARY KEY,
                    learning_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_question TEXT NOT NULL,
                    source_answer TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    trace_id TEXT,
                    project_id TEXT,
                    importance REAL NOT NULL DEFAULT 0.5,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_learning_type ON learning(learning_type);
                CREATE INDEX IF NOT EXISTS idx_learning_project ON learning(project_id);
                CREATE INDEX IF NOT EXISTS idx_learning_trace ON learning(trace_id);
                CREATE INDEX IF NOT EXISTS idx_learning_confidence ON learning(confidence DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_created ON learning(created_at DESC);
            """)
            self._conn.commit()
        self._initialized = True

    def extract_learning(
        self,
        question: str,
        answer: str,
        confidence: float,
        project_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Extract learning from a completed task."""
        if not self._initialized:
            self.initialize()

        trace_id = trace_id or str(uuid4())
        items = []

        # Extract different types of learning based on content and confidence
        learnings = self._analyze_for_learning(question, answer, confidence)

        import json
        with self._lock:
            for learning in learnings:
                learning_id = str(uuid4())
                item = LearningItem(
                    id=learning_id,
                    learning_type=learning["type"],
                    content=learning["content"],
                    source_question=question,
                    source_answer=answer,
                    confidence=confidence,
                    trace_id=trace_id,
                    project_id=project_id,
                    importance=learning["importance"],
                    tags=learning["tags"],
                    metadata={"extracted_from": "reflection"},
                )

                self._conn.execute(
                    """INSERT INTO learning
                       (id, learning_type, content, source_question, source_answer,
                        confidence, trace_id, project_id, importance, tags, created_at, metadata)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        item.id,
                        item.learning_type,
                        item.content,
                        item.source_question,
                        item.source_answer,
                        item.confidence,
                        item.trace_id,
                        item.project_id,
                        item.importance,
                        json.dumps(item.tags, ensure_ascii=False),
                        item.created_at,
                        json.dumps(item.metadata, ensure_ascii=False),
                    ),
                )
                items.append(item)

            self._conn.commit()

        return asdict(LearningResult(
            stored_count=len(items),
            items=items,
        ))

    def _analyze_for_learning(
        self,
        question: str,
        answer: str,
        confidence: float,
    ) -> list[dict[str, Any]]:
        """Analyze Q&A to extract learning (simplified - would use LLM)."""
        learnings = []
        a_lower = answer.lower()

        # Always store the experience
        learnings.append({
            "type": LearningType.EXPERIENCE,
            "content": f"Q: {question}\nA: {answer[:500]}",
            "importance": 0.5,
            "tags": ["auto-extracted"],
        })

        # If decision-like content
        decision_keywords = ["decide", "decision", "decided", "rule", "policy", "require", "must", "should"]
        if any(kw in a_lower for kw in decision_keywords):
            learnings.append({
                "type": LearningType.DECISION,
                "content": f"Decision derived from: {question}\nResolution: {answer[:500]}",
                "importance": 0.75,
                "tags": ["decision", "auto-extracted"],
            })

        # If lesson-like content
        lesson_keywords = ["lesson", "learned", "never again", "avoid", "pitfall", "mistake"]
        if any(kw in a_lower for kw in lesson_keywords):
            learnings.append({
                "type": LearningType.LESSON,
                "content": f"Lesson from: {question}\nLearning: {answer[:500]}",
                "importance": 0.7,
                "tags": ["lesson", "auto-extracted"],
            })

        # If strategy-like content
        strategy_keywords = ["strategy", "approach", "method", "process", "workflow", "steps"]
        if any(kw in a_lower for kw in strategy_keywords):
            learnings.append({
                "type": LearningType.STRATEGY,
                "content": f"Strategy for: {question}\nApproach: {answer[:500]}",
                "importance": 0.65,
                "tags": ["strategy", "auto-extracted"],
            })

        # Classify as success or failure based on confidence
        if confidence >= 0.8:
            learnings.append({
                "type": LearningType.SUCCESS,
                "content": f"Successful resolution: {question}\nAnswer: {answer[:500]}",
                "importance": 0.6,
                "tags": ["success", "high-confidence"],
            })
        elif confidence < 0.4:
            learnings.append({
                "type": LearningType.FAILURE,
                "content": f"Low confidence resolution: {question}\nAnswer: {answer[:500]}",
                "importance": 0.5,
                "tags": ["failure", "low-confidence", "needs-review"],
            })

        return learnings

    def get_learning(
        self,
        learning_id: str,
    ) -> LearningItem | None:
        """Get a learning item by ID."""
        if not self._initialized:
            self.initialize()

        import json
        with self._lock:
            row = self._conn.execute("SELECT * FROM learning WHERE id=?", (learning_id,)).fetchone()
        if not row:
            return None

        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        item["metadata"] = json.loads(item["metadata"])
        return LearningItem(**item)

    def search_learning(
        self,
        query: str,
        learning_type: str | None = None,
        project_id: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search learning items."""
        if not self._initialized:
            self.initialize()

        sql = "SELECT * FROM learning WHERE 1=1"
        values = []

        if learning_type:
            sql += " AND learning_type = ?"
            values.append(learning_type)
        if project_id:
            sql += " AND project_id = ?"
            values.append(project_id)
        if min_confidence > 0:
            sql += " AND confidence >= ?"
            values.append(min_confidence)
        if query:
            keywords = query.lower().split()
            conditions = []
            for kw in keywords[:3]:
                conditions.append("content LIKE ?")
                values.append(f"%{kw}%")
            if conditions:
                sql += " AND (" + " OR ".join(conditions) + ")"

        sql += " ORDER BY confidence DESC, importance DESC, created_at DESC LIMIT ?"
        values.append(limit)

        import json
        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item["tags"])
            item["metadata"] = json.loads(item["metadata"])
            results.append(item)
        return results

    def get_lessons(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get all lessons learned."""
        return self.search_learning("", learning_type=LearningType.LESSON, project_id=project_id, limit=limit)

    def get_decisions(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get all decisions."""
        return self.search_learning("", learning_type=LearningType.DECISION, project_id=project_id, limit=limit)

    def get_strategies(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get all strategies."""
        return self.search_learning("", learning_type=LearningType.STRATEGY, project_id=project_id, limit=limit)

    def get_failures(self, project_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Get failures for review."""
        return self.search_learning("", learning_type=LearningType.FAILURE, project_id=project_id, limit=limit)

    def close(self) -> None:
        """Close database connection."""
        if self._lock:
            with self._lock:
                self._conn.close()
