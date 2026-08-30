"""Mid Brain Reflection Engine - Post-task reflection and analysis."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


@dataclass(slots=True)
class ReflectionRecord:
    """A reflection record after completing a task."""
    id: str
    question: str
    answer: str
    confidence: float
    trace_id: str
    project_id: str | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    what_we_knew: str = ""
    what_we_assumed: str = ""
    evidence_used: str = ""
    what_was_correct: str = ""
    what_was_wrong: str = ""
    what_changed_conclusion: str = ""
    what_to_remember: str = ""
    what_to_deprecate: str = ""
    what_to_improve: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))


@dataclass(slots=True)
class ReflectionPrompt:
    """Structured reflection prompts."""
    prompts = [
        "What did we know before starting?",
        "What did we assume?",
        "What evidence was used?",
        "What was correct?",
        "What was wrong?",
        "What changed our conclusion?",
        "What should be remembered?",
        "What should be deprecated?",
        "What should improve next time?",
    ]


class ReflectionEngine:
    """
    Reflection Engine for Mid Brain.

    After important tasks, Mid Brain reflects on:
    1. What did we know?
    2. What did we assume?
    3. What evidence was used?
    4. What was correct?
    5. What was wrong?
    6. What changed our conclusion?
    7. What should be remembered?
    8. What should be deprecated?
    9. What should improve next time?

    Stores: Experience, Decision, Lesson, Strategy, Failure, Success
    """

    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/reflection.db") -> None:
        self.mid_brain = mid_brain
        self.db_path = db_path
        from pathlib import Path
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
                CREATE TABLE IF NOT EXISTS reflections (
                    id TEXT PRIMARY KEY,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    trace_id TEXT,
                    project_id TEXT,
                    steps TEXT NOT NULL DEFAULT '[]',
                    what_we_knew TEXT,
                    what_we_assumed TEXT,
                    evidence_used TEXT,
                    what_was_correct TEXT,
                    what_was_wrong TEXT,
                    what_changed_conclusion TEXT,
                    what_to_remember TEXT,
                    what_to_deprecate TEXT,
                    what_to_improve TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reflection_trace ON reflections(trace_id);
                CREATE INDEX IF NOT EXISTS idx_reflection_project ON reflections(project_id);
                CREATE INDEX IF NOT EXISTS idx_reflection_created ON reflections(created_at DESC);
            """)
            self._conn.commit()
        self._initialized = True

    def reflect(
        self,
        question: str,
        answer: str,
        confidence: float,
        steps: list[dict[str, Any]],
        project_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Perform structured reflection after a task."""
        if not self._initialized:
            self.initialize()

        trace_id = trace_id or str(uuid4())
        reflection_id = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # Generate reflection content (in full impl, would use LLM)
        reflection_content = self._generate_reflection(question, answer, confidence, steps)

        import json
        with self._lock:
            self._conn.execute(
                """INSERT INTO reflections
                   (id, question, answer, confidence, trace_id, project_id, steps,
                    what_we_knew, what_we_assumed, evidence_used,
                    what_was_correct, what_was_wrong, what_changed_conclusion,
                    what_to_remember, what_to_deprecate, what_to_improve, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    reflection_id,
                    question,
                    answer,
                    confidence,
                    trace_id,
                    project_id,
                    json.dumps(steps, ensure_ascii=False),
                    reflection_content["what_we_knew"],
                    reflection_content["what_we_assumed"],
                    reflection_content["evidence_used"],
                    reflection_content["what_was_correct"],
                    reflection_content["what_was_wrong"],
                    reflection_content["what_changed_conclusion"],
                    reflection_content["what_to_remember"],
                    reflection_content["what_to_deprecate"],
                    reflection_content["what_to_improve"],
                    now,
                ),
            )
            self._conn.commit()

        return {"stored": True, "reflection_id": reflection_id, **reflection_content}

    def _generate_reflection(
        self,
        question: str,
        answer: str,
        confidence: float,
        steps: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Generate reflection content (simplified - would use LLM in production)."""
        # Extract key info from steps
        memories_used = 0
        conflicts = 0
        for step in steps:
            if step.get("phase") == "RECALL":
                memories_used = step.get("output", {}).get("results_count", 0)
            elif step.get("phase") == "CONFLICT_DETECTION":
                conflicts = step.get("output", {}).get("conflicts_count", 0)

        return {
            "what_we_knew": f"Retrieved {memories_used} relevant memories from Mid Brain. "
                           f"Question was about: {question[:100]}",
            "what_we_assumed": f"Assumed confidence threshold of {self.mid_brain.config.confidence_threshold} "
                              f"was sufficient for storage. Assumed First/Second Brain would be available.",
            "evidence_used": f"Mid Brain memories: {memories_used} items. "
                           f"Conflicts detected: {conflicts}. "
                           f"Final confidence: {confidence:.2f}",
            "what_was_correct": f"Answer synthesized with confidence {confidence:.2f}. "
                               f"Sources were properly cited." if confidence > 0.7
                               else "Low confidence - answer may be incomplete",
            "what_was_wrong": "Confidence below threshold" if confidence < 0.5 else "No major errors detected",
            "what_changed_conclusion": f"Confidence calculation based on {conflicts} conflicts and evidence quality"
                                      if conflicts else "No conflicts changed the conclusion",
            "what_to_remember": f"Question pattern: {question[:80]}. "
                               f"Confidence: {confidence:.2f}. "
                               f"Answer approach: {'synthesis' if 'Both brains' in answer else 'single source'}",
            "what_to_deprecate": "No deprecations identified" if confidence > 0.6
                                 else "Consider reviewing low-confidence answers",
            "what_to_improve": "Improve conflict resolution" if conflicts > 0
                              else "Consider gathering more evidence for higher confidence",
        }

    def get_reflection(self, reflection_id: str) -> dict[str, Any] | None:
        """Get a reflection by ID."""
        if not self._initialized:
            self.initialize()

        import json
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM reflections WHERE id=?", (reflection_id,)
            ).fetchone()
        if not row:
            return None

        item = dict(row)
        item["steps"] = json.loads(item["steps"])
        return item

    def get_reflections_for_question(self, question: str, limit: int = 5) -> list[dict[str, Any]]:
        """Get past reflections for similar questions."""
        if not self._initialized:
            self.initialize()

        import json
        sql = "SELECT * FROM reflections WHERE question LIKE ? ORDER BY created_at DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (f"%{question}%", limit)).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["steps"] = json.loads(item["steps"])
            results.append(item)
        return results

    def get_recent_reflections(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent reflections."""
        if not self._initialized:
            self.initialize()

        import json
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM reflections ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["steps"] = json.loads(item["steps"])
            results.append(item)
        return results

    def close(self) -> None:
        """Close database connection."""
        if self._lock:
            with self._lock:
                self._conn.close()
