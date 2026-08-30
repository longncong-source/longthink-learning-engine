"""Adaptive Cognitive Network for Mid Brain - Dynamic knowledge/reasoning graph."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class CognitiveNode:
    """Node in the cognitive network."""

    node_id: str = field(default_factory=lambda: uuid4().hex[:12])
    type: str = ""  # question, answer, knowledge, experience, decision, lesson, strategy, evidence, conflict, outcome, reasoning
    content: str = ""
    project_id: str | None = None
    confidence: float = 0.5
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(slots=True)
class CognitiveEdge:
    """Edge in the cognitive network."""

    edge_id: str = field(default_factory=lambda: uuid4().hex[:12])
    source_id: str = ""
    target_id: str = ""
    relation: str = ""  # supports, contradicts, derived_from, similar_to, depends_on, causes, solves, refines, verified_by, used_in, failed_in
    weight: float = 1.0
    confidence: float = 0.5
    frequency: int = 1
    success_rate: float = 0.5
    last_used: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


class AdaptiveCognitiveNetwork:
    """
    Dynamic knowledge/reasoning graph that adapts based on:
    - success/failure
    - feedback
    - evidence
    - usage
    - contradiction
    """

    VALID_RELATIONS = frozenset({
        "supports",
        "contradicts",
        "derived_from",
        "similar_to",
        "depends_on",
        "causes",
        "solves",
        "refines",
        "verified_by",
        "used_in",
        "failed_in",
    })

    def __init__(self, db_path: str | Path = "mid_brain_network.db") -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def initialize(self) -> None:
        """Initialize the adaptive network (already done in __init__)."""
        pass

    def _init_db(self) -> None:
        """Initialize database schema."""
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Nodes table
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                project_id TEXT,
                confidence REAL DEFAULT 0.5,
                importance REAL DEFAULT 0.5,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project_id);
            CREATE INDEX IF NOT EXISTS idx_nodes_confidence ON nodes(confidence DESC);

            CREATE TABLE IF NOT EXISTS edges (
                edge_id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                confidence REAL DEFAULT 0.5,
                frequency INTEGER DEFAULT 1,
                success_rate REAL DEFAULT 0.5,
                last_used TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY (source_id) REFERENCES nodes(node_id),
                FOREIGN KEY (target_id) REFERENCES nodes(node_id)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
            CREATE INDEX IF NOT EXISTS idx_edges_weight ON edges(weight DESC);
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ Node Operations

    def add_node(
        self,
        type: str,
        content: str,
        project_id: str | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> CognitiveNode:
        """Add a new node to the network."""
        node = CognitiveNode(
            type=type,
            content=content,
            project_id=project_id,
            confidence=confidence,
            importance=importance,
            metadata=metadata or {},
        )

        self._conn.execute("""
            INSERT INTO nodes (node_id, type, content, project_id, confidence, importance, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            node.node_id,
            node.type,
            node.content,
            node.project_id,
            node.confidence,
            node.importance,
            json.dumps(node.metadata),
            node.created_at,
            node.updated_at,
        ))
        self._conn.commit()
        return node

    def get_node(self, node_id: str) -> CognitiveNode | None:
        """Get node by ID."""
        row = self._conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if not row:
            return None
        return self._row_to_node(row)

    def update_node(self, node_id: str, updates: dict[str, Any]) -> bool:
        """Update node fields."""
        allowed = {"type", "content", "confidence", "importance", "metadata"}
        updates = {k: v for k, v in updates.items() if k in allowed}
        if not updates:
            return False

        updates["updated_at"] = datetime.now().isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [node_id]

        self._conn.execute(f"UPDATE nodes SET {set_clause} WHERE node_id = ?", values)
        self._conn.commit()
        return True

    def search_nodes(
        self,
        query: str,
        type: str | None = None,
        project_id: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> list[CognitiveNode]:
        """Search nodes by content (simple text search)."""
        sql = "SELECT * FROM nodes WHERE content LIKE ?"
        params = [f"%{query}%"]

        if type:
            sql += " AND type = ?"
            params.append(type)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        if min_confidence > 0:
            sql += " AND confidence >= ?"
            params.append(min_confidence)

        sql += " ORDER BY confidence DESC, importance DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_node(row) for row in rows]

    # ------------------------------------------------------------------ Edge Operations

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        weight: float = 1.0,
        confidence: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> CognitiveEdge | None:
        """Add or update an edge between nodes."""
        if relation not in self.VALID_RELATIONS:
            raise ValueError(f"Invalid relation: {relation}. Valid: {self.VALID_RELATIONS}")

        # Check if edge exists
        existing = self._conn.execute(
            "SELECT * FROM edges WHERE source_id = ? AND target_id = ? AND relation = ?",
            (source_id, target_id, relation),
        ).fetchone()

        if existing:
            # Update existing edge - increase frequency, update weight
            new_freq = existing["frequency"] + 1
            # Adaptive weight: increase if successful, decrease if failed
            new_weight = min(2.0, existing["weight"] + 0.1)

            self._conn.execute("""
                UPDATE edges SET frequency = ?, weight = ?, last_used = ?, metadata = ?
                WHERE edge_id = ?
            """, (new_freq, new_weight, datetime.now().isoformat(), json.dumps(metadata or {}), existing["edge_id"]))
            self._conn.commit()
            return self._row_to_edge(existing)

        edge = CognitiveEdge(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=weight,
            confidence=confidence,
            metadata=metadata or {},
        )

        self._conn.execute("""
            INSERT INTO edges (edge_id, source_id, target_id, relation, weight, confidence, frequency, last_used, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            edge.edge_id,
            edge.source_id,
            edge.target_id,
            edge.relation,
            edge.weight,
            edge.confidence,
            edge.frequency,
            edge.last_used,
            json.dumps(edge.metadata),
        ))
        self._conn.commit()
        return edge

    def get_edges(
        self,
        node_id: str,
        direction: str = "both",  # "out", "in", "both"
        relation: str | None = None,
    ) -> list[CognitiveEdge]:
        """Get edges for a node."""
        if direction == "out":
            sql = "SELECT * FROM edges WHERE source_id = ?"
        elif direction == "in":
            sql = "SELECT * FROM edges WHERE target_id = ?"
        else:
            sql = "SELECT * FROM edges WHERE source_id = ? OR target_id = ?"

        params = [node_id] if direction != "both" else [node_id, node_id]

        if relation:
            sql += " AND relation = ?"
            params.append(relation)

        sql += " ORDER BY weight DESC, confidence DESC"

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_edge(row) for row in rows]

    def strengthen_edge(self, edge_id: str, success: bool = True) -> bool:
        """Strengthen or weaken an edge based on outcome."""
        row = self._conn.execute("SELECT * FROM edges WHERE edge_id = ?", (edge_id,)).fetchone()
        if not row:
            return False

        # Update success rate
        freq = row["frequency"]
        sr = row["success_rate"]
        new_sr = (sr * (freq - 1) + (1.0 if success else 0.0)) / freq

        # Update weight based on success
        weight = row["weight"]
        if success:
            weight = min(2.0, weight * 1.1)
        else:
            weight = max(0.1, weight * 0.9)

        self._conn.execute("""
            UPDATE edges SET weight = ?, success_rate = ?, last_used = ?
            WHERE edge_id = ?
        """, (weight, new_sr, datetime.now().isoformat(), edge_id))
        self._conn.commit()
        return True

    # ------------------------------------------------------------------ Network Queries

    def get_subgraph(
        self,
        center_node_id: str,
        depth: int = 2,
        min_weight: float = 0.3,
    ) -> dict[str, Any]:
        """Get subgraph around a center node."""
        visited = set()
        nodes = {}
        edges = []

        def traverse(node_id: str, current_depth: int) -> None:
            if current_depth > depth or node_id in visited:
                return
            visited.add(node_id)

            node = self.get_node(node_id)
            if node:
                nodes[node.node_id] = node

            for edge in self.get_edges(node_id):
                if edge.weight < min_weight:
                    continue
                edges.append(edge)
                other_id = edge.target_id if edge.source_id == node_id else edge.source_id
                if other_id not in visited:
                    traverse(other_id, current_depth + 1)

        traverse(center_node_id, 0)
        return {"nodes": list(nodes.values()), "edges": edges}

    def find_path(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 4,
    ) -> list[CognitiveNode] | None:
        """Find path between two nodes (BFS)."""
        from collections import deque

        queue = deque([(source_id, [source_id])])
        visited = {source_id}

        while queue:
            current, path = queue.popleft()
            if len(path) > max_depth:
                continue

            if current == target_id:
                return [self.get_node(nid) for nid in path if self.get_node(nid)]

            for edge in self.get_edges(current, direction="out"):
                if edge.weight < 0.3:
                    continue
                next_id = edge.target_id
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, path + [next_id]))

        return None

    def get_related_nodes(
        self,
        node_id: str,
        relation: str | None = None,
        min_weight: float = 0.5,
        limit: int = 10,
    ) -> list[tuple[CognitiveNode, CognitiveEdge]]:
        """Get nodes related to a given node."""
        edges = self.get_edges(node_id, direction="both", relation=relation)
        results = []

        for edge in edges:
            if edge.weight < min_weight:
                continue
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            node = self.get_node(other_id)
            if node:
                results.append((node, edge))
            if len(results) >= limit:
                break

        return results

    # ------------------------------------------------------------------ Adaptation

    def record_usage(self, node_id: str, success: bool = True) -> None:
        """Record usage of a node for adaptation."""
        node = self.get_node(node_id)
        if not node:
            return

        # Update importance based on usage
        new_importance = min(1.0, node.importance + 0.02 if success else max(0.1, node.importance - 0.01))
        self.update_node(node_id, {"importance": new_importance})

        # Update connected edges
        for edge in self.get_edges(node_id):
            self.strengthen_edge(edge.edge_id, success)

    def record_feedback(self, node_id: str, feedback: str, positive: bool = True) -> None:
        """Record human feedback for adaptation."""
        node = self.get_node(node_id)
        if not node:
            return

        # Adjust confidence based on feedback
        if positive:
            new_conf = min(1.0, node.confidence + 0.1)
        else:
            new_conf = max(0.0, node.confidence - 0.15)

        self.update_node(node_id, {
            "confidence": new_conf,
            "metadata": {**node.metadata, "last_feedback": feedback, "feedback_positive": positive},
        })

    def get_stats(self) -> dict[str, Any]:
        """Get network statistics."""
        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        type_counts = dict(self._conn.execute("SELECT type, COUNT(*) FROM nodes GROUP BY type").fetchall())
        relation_counts = dict(self._conn.execute("SELECT relation, COUNT(*) FROM edges GROUP BY relation").fetchall())

        avg_confidence = self._conn.execute("SELECT AVG(confidence) FROM nodes").fetchone()[0] or 0
        avg_weight = self._conn.execute("SELECT AVG(weight) FROM edges").fetchone()[0] or 0

        return {
            "nodes": node_count,
            "edges": edge_count,
            "node_types": type_counts,
            "edge_relations": relation_counts,
            "avg_confidence": round(avg_confidence, 3),
            "avg_edge_weight": round(avg_weight, 3),
        }

    # ------------------------------------------------------------------ Helpers

    def _row_to_node(self, row: sqlite3.Row) -> CognitiveNode:
        import json
        return CognitiveNode(
            node_id=row["node_id"],
            type=row["type"],
            content=row["content"],
            project_id=row["project_id"],
            confidence=row["confidence"],
            importance=row["importance"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_edge(self, row: sqlite3.Row) -> CognitiveEdge:
        import json
        return CognitiveEdge(
            edge_id=row["edge_id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=row["relation"],
            weight=row["weight"],
            confidence=row["confidence"],
            frequency=row["frequency"],
            success_rate=row["success_rate"],
            last_used=row["last_used"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> AdaptiveCognitiveNetwork:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
