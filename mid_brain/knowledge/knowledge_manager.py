"""Mid Brain Knowledge Manager - Validated knowledge with versioning and promotion."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


class KnowledgeType:
    FACT = "fact"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    UNKNOWN = "unknown"


class KnowledgeStatus:
    CANDIDATE = "candidate"
    VALIDATED = "validated"
    TRUSTED = "trusted"
    MASTER = "master"
    DEPRECATED = "deprecated"
    REJECTED = "rejected"


@dataclass(slots=True)
class KnowledgeItem:
    """A validated knowledge item with full provenance."""
    id: str
    content: str
    knowledge_type: str = KnowledgeType.FACT
    status: str = KnowledgeStatus.CANDIDATE
    source: str = "mid-brain"
    project_id: str | None = None
    confidence: float = 0.5
    importance: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)
    version: int = 1
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    updated_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    validated_at: str | None = None
    validated_by: str | None = None


@dataclass(slots=True)
class KnowledgeVersion:
    """A version snapshot of a knowledge item."""
    knowledge_id: str
    version: int
    content: str
    status: str
    confidence: float
    importance: float
    changed_by: str
    changed_at: str
    change_reason: str


class KnowledgeManager:
    """
    Master Knowledge Model for Mid Brain.

    Knowledge lifecycle:
    CANDIDATE → VALIDATED → TRUSTED → MASTER
                    ↘ DEPRECATED
                    ↘ REJECTED

    Every change creates a new version - history is never overwritten.
    """

    VALID_TYPES = {KnowledgeType.FACT, KnowledgeType.INFERENCE, KnowledgeType.HYPOTHESIS,
                   KnowledgeType.OPINION, KnowledgeType.UNKNOWN}
    VALID_STATUSES = {KnowledgeStatus.CANDIDATE, KnowledgeStatus.VALIDATED,
                      KnowledgeStatus.TRUSTED, KnowledgeStatus.MASTER,
                      KnowledgeStatus.DEPRECATED, KnowledgeStatus.REJECTED}

    def __init__(self, mid_brain: MidBrain, db_path: str = "mid_brain_data/knowledge.db") -> None:
        self.mid_brain = mid_brain
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
                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    knowledge_type TEXT NOT NULL DEFAULT 'fact',
                    status TEXT NOT NULL DEFAULT 'candidate',
                    source TEXT NOT NULL DEFAULT 'mid-brain',
                    project_id TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    importance REAL NOT NULL DEFAULT 0.5,
                    provenance TEXT NOT NULL DEFAULT '{}',
                    evidence TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    validated_at TEXT,
                    validated_by TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_knowledge_status ON knowledge(status);
                CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge(knowledge_type);
                CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge(project_id);
                CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge(created_at DESC);

                CREATE TABLE IF NOT EXISTS knowledge_versions (
                    knowledge_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    importance REAL NOT NULL,
                    changed_by TEXT NOT NULL,
                    changed_at TEXT NOT NULL,
                    change_reason TEXT,
                    PRIMARY KEY (knowledge_id, version),
                    FOREIGN KEY (knowledge_id) REFERENCES knowledge(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_versions_knowledge ON knowledge_versions(knowledge_id);
            """)
            self._conn.commit()
        self._initialized = True

    def create_knowledge(
        self,
        content: str,
        kind: str | None = None,
        importance: float | None = None,
        confidence: float | None = None,
        source: str = "mid-brain",
        project_id: str | None = None,
        evidence: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new knowledge candidate."""
        if not self._initialized:
            self.initialize()

        knowledge_id = str(uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        ktype = kind or KnowledgeType.FACT
        if ktype not in self.VALID_TYPES:
            ktype = KnowledgeType.FACT

        item = KnowledgeItem(
            id=knowledge_id,
            content=content,
            knowledge_type=ktype,
            status=KnowledgeStatus.CANDIDATE,
            source=source,
            project_id=project_id,
            confidence=confidence or 0.5,
            importance=importance or 0.5,
            provenance={"created_by": source, "created_at": now},
            evidence=evidence or [],
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            self._conn.execute(
                """INSERT INTO knowledge
                   (id, content, knowledge_type, status, source, project_id,
                    confidence, importance, provenance, evidence, version, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    item.id,
                    item.content,
                    item.knowledge_type,
                    item.status,
                    item.source,
                    item.project_id,
                    item.confidence,
                    item.importance,
                    json.dumps(item.provenance, ensure_ascii=False),
                    json.dumps(item.evidence, ensure_ascii=False),
                    item.version,
                    item.created_at,
                    item.updated_at,
                ),
            )
            # Create initial version
            self._conn.execute(
                """INSERT INTO knowledge_versions
                   (knowledge_id, version, content, status, confidence, importance,
                    changed_by, changed_at, change_reason)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    item.id, 1, item.content, item.status,
                    item.confidence, item.importance,
                    source, now, "Initial creation"
                ),
            )
            self._conn.commit()

        return {"created": True, "knowledge_id": knowledge_id, "item": self._item_to_dict(item)}

    def validate_knowledge(
        self,
        knowledge_id: str,
        validated_by: str = "mid-brain",
        evidence: list[str] | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        """Promote candidate to validated."""
        return self._change_status(knowledge_id, KnowledgeStatus.VALIDATED, validated_by, evidence, confidence)

    def promote_knowledge(
        self,
        knowledge_id: str,
        new_status: str,
        promoted_by: str = "mid-brain",
        evidence: list[str] | None = None,
        confidence: float | None = None,
    ) -> dict[str, Any]:
        """Promote knowledge to higher status (validated → trusted → master)."""
        if new_status not in {KnowledgeStatus.VALIDATED, KnowledgeStatus.TRUSTED, KnowledgeStatus.MASTER}:
            return {"success": False, "error": f"Invalid promotion status: {new_status}"}
        return self._change_status(knowledge_id, new_status, promoted_by, evidence, confidence)

    def deprecate_knowledge(
        self,
        knowledge_id: str,
        deprecated_by: str = "mid-brain",
        reason: str = "",
    ) -> dict[str, Any]:
        """Mark knowledge as deprecated."""
        return self._change_status(knowledge_id, KnowledgeStatus.DEPRECATED, deprecated_by, None, None, reason)

    def reject_knowledge(
        self,
        knowledge_id: str,
        rejected_by: str = "mid-brain",
        reason: str = "",
    ) -> dict[str, Any]:
        """Reject knowledge."""
        return self._change_status(knowledge_id, KnowledgeStatus.REJECTED, rejected_by, None, None, reason)

    def update_knowledge(
        self,
        knowledge_id: str,
        content: str | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        evidence: list[str] | None = None,
        updated_by: str = "mid-brain",
        reason: str = "Updated",
    ) -> dict[str, Any]:
        """Update knowledge content (creates new version)."""
        if not self._initialized:
            self.initialize()

        item = self.get(knowledge_id)
        if not item:
            return {"success": False, "error": "Knowledge not found"}

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        new_version = item.version + 1

        updates = {}
        if content is not None:
            updates["content"] = content
        if confidence is not None:
            updates["confidence"] = confidence
        if importance is not None:
            updates["importance"] = importance
        if evidence is not None:
            updates["evidence"] = evidence

        updates["version"] = new_version
        updates["updated_at"] = now

        # Build provenance addition
        provenance = item.provenance.copy()
        provenance["last_updated_by"] = updated_by
        provenance["last_updated_at"] = now
        provenance["last_change_reason"] = reason
        updates["provenance"] = provenance

        sets = []
        values = []
        for key, value in updates.items():
            if key in ("provenance", "evidence"):
                sets.append(f"{key} = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                sets.append(f"{key} = ?")
                values.append(value)

        values.append(knowledge_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE knowledge SET {', '.join(sets)} WHERE id=?",
                values,
            )
            # Add version record
            self._conn.execute(
                """INSERT INTO knowledge_versions
                   (knowledge_id, version, content, status, confidence, importance,
                    changed_by, changed_at, change_reason)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    knowledge_id, new_version,
                    content or item.content,
                    item.status,
                    confidence or item.confidence,
                    importance or item.importance,
                    updated_by, now, reason
                ),
            )
            self._conn.commit()

        return {"success": True, "knowledge_id": knowledge_id, "version": new_version}

    def get_knowledge_history(self, knowledge_id: str) -> list[dict[str, Any]]:
        """Get full version history of a knowledge item."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM knowledge_versions WHERE knowledge_id=? ORDER BY version",
                (knowledge_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get(self, knowledge_id: str) -> KnowledgeItem | None:
        """Get a knowledge item by ID."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM knowledge WHERE id=?", (knowledge_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def search(
        self,
        query: str,
        project_id: str | None = None,
        status: str | None = None,
        knowledge_type: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search knowledge items."""
        if not self._initialized:
            self.initialize()

        sql = "SELECT * FROM knowledge WHERE 1=1"
        values = []

        if project_id:
            sql += " AND project_id = ?"
            values.append(project_id)
        if status:
            sql += " AND status = ?"
            values.append(status)
        if knowledge_type:
            sql += " AND knowledge_type = ?"
            values.append(knowledge_type)
        if min_confidence > 0:
            sql += " AND confidence >= ?"
            values.append(min_confidence)
        if query:
            sql += " AND content LIKE ?"
            values.append(f"%{query}%")

        sql += " ORDER BY confidence DESC, importance DESC, created_at DESC LIMIT ?"
        values.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, values).fetchall()

        items = [self._row_to_item(r) for r in rows]
        return {
            "results": [self._item_to_dict(item) for item in items],
            "total": len(items),
            "query": query,
        }

    def get_trusted_knowledge(self, query: str, project_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        """Get only TRUSTED or MASTER knowledge for high-confidence answers."""
        return self.search(
            query=query,
            project_id=project_id,
            status=KnowledgeStatus.TRUSTED,  # Will only match TRUSTED
            min_confidence=0.75,
            limit=limit,
        )["results"] + self.search(
            query=query,
            project_id=project_id,
            status=KnowledgeStatus.MASTER,
            min_confidence=0.9,
            limit=limit,
        )["results"]

    def _change_status(
        self,
        knowledge_id: str,
        new_status: str,
        changed_by: str,
        evidence: list[str] | None = None,
        confidence: float | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        """Internal method to change knowledge status."""
        if not self._initialized:
            self.initialize()

        if new_status not in self.VALID_STATUSES:
            return {"success": False, "error": f"Invalid status: {new_status}"}

        item = self.get(knowledge_id)
        if not item:
            return {"success": False, "error": "Knowledge not found"}

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        new_version = item.version + 1

        updates = {
            "status": new_status,
            "version": new_version,
            "updated_at": now,
        }
        if evidence is not None:
            updates["evidence"] = evidence
        if confidence is not None:
            updates["confidence"] = confidence
        if new_status in {KnowledgeStatus.VALIDATED, KnowledgeStatus.TRUSTED, KnowledgeStatus.MASTER}:
            updates["validated_at"] = now
            updates["validated_by"] = changed_by

        # Update provenance
        provenance = item.provenance.copy()
        provenance[f"{new_status.lower()}_by"] = changed_by
        provenance[f"{new_status.lower()}_at"] = now
        if reason:
            provenance[f"{new_status.lower()}_reason"] = reason
        updates["provenance"] = provenance

        sets = []
        values = []
        for key, value in updates.items():
            if key in ("provenance", "evidence"):
                sets.append(f"{key} = ?")
                values.append(json.dumps(value, ensure_ascii=False))
            else:
                sets.append(f"{key} = ?")
                values.append(value)

        values.append(knowledge_id)

        with self._lock:
            self._conn.execute(
                f"UPDATE knowledge SET {', '.join(sets)} WHERE id=?",
                values,
            )
            # Add version record
            self._conn.execute(
                """INSERT INTO knowledge_versions
                   (knowledge_id, version, content, status, confidence, importance,
                    changed_by, changed_at, change_reason)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    knowledge_id, new_version, item.content, new_status,
                    confidence or item.confidence, item.importance,
                    changed_by, now, reason or f"Status changed to {new_status}"
                ),
            )
            self._conn.commit()

        return {"success": True, "knowledge_id": knowledge_id, "status": new_status, "version": new_version}

    # ------------------------------------------------------------------ helpers

    def _row_to_item(self, row: sqlite3.Row) -> KnowledgeItem:
        return KnowledgeItem(
            id=row["id"],
            content=row["content"],
            knowledge_type=row["knowledge_type"],
            status=row["status"],
            source=row["source"],
            project_id=row["project_id"],
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            provenance=json.loads(row["provenance"]) if row["provenance"] else {},
            evidence=json.loads(row["evidence"]) if row["evidence"] else [],
            version=int(row["version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            validated_at=row["validated_at"],
            validated_by=row["validated_by"],
        )

    def _item_to_dict(self, item: KnowledgeItem) -> dict[str, Any]:
        return {
            "id": item.id,
            "content": item.content,
            "knowledge_type": item.knowledge_type,
            "status": item.status,
            "source": item.source,
            "project_id": item.project_id,
            "confidence": item.confidence,
            "importance": item.importance,
            "provenance": item.provenance,
            "evidence": item.evidence,
            "version": item.version,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "validated_at": item.validated_at,
            "validated_by": item.validated_by,
        }

    def close(self) -> None:
        """Close database connection."""
        with self._lock:
            self._conn.close()
