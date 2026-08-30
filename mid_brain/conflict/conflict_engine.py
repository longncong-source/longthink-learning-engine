"""Mid Brain Conflict Engine - Detect and resolve contradictions between brains."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


class ConflictSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConflictStatus(Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    ACCEPTED_AS_UNCERTAIN = "accepted_as_uncertain"


@dataclass(slots=True)
class ConflictObject:
    """A detected conflict between brain answers."""
    conflict_id: str
    claim_a: str
    claim_b: str
    source_a: str
    source_b: str
    evidence_a: list[str] = field(default_factory=list)
    evidence_b: list[str] = field(default_factory=list)
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    status: ConflictStatus = ConflictStatus.OPEN
    resolution: str | None = None
    confidence: float = 0.5
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    resolved_at: str | None = None
    question_context: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ConflictEngine:
    """
    Contradiction Detection Engine.

    When First Brain and Second Brain give different answers:
    1. Detect the conflict
    2. Compare claims
    3. Request/evaluate evidence
    4. Resolve or mark as uncertain
    5. Never randomly choose - must have reasoned resolution
    """

    def __init__(self, mid_brain: MidBrain) -> None:
        self.mid_brain = mid_brain
        self._conflicts: dict[str, ConflictObject] = {}
        self._initialized = False

    def initialize(self) -> None:
        """Initialize conflict engine."""
        self._initialized = True

    def detect(
        self,
        first_brain_answer: str | None,
        second_brain_answer: str | None,
        question: str,
    ) -> list[dict[str, Any]]:
        """Detect conflicts between two answers."""
        if not first_brain_answer or not second_brain_answer:
            return []

        conflicts = []

        # Simple contradiction detection based on keywords
        fb_lower = first_brain_answer.lower()
        sb_lower = second_brain_answer.lower()

        # Check for explicit negations
        negation_pairs = [
            ("yes", "no"), ("true", "false"), ("correct", "incorrect"),
            ("is", "is not"), ("was", "was not"), ("will", "will not"),
            ("can", "cannot"), ("should", "should not"), ("must", "must not"),
            ("increase", "decrease"), ("more", "less"), ("before", "after"),
            ("approve", "reject"), ("accept", "deny"), ("valid", "invalid"),
        ]

        for pos, neg in negation_pairs:
            fb_has_pos = pos in fb_lower
            fb_has_neg = neg in fb_lower
            sb_has_pos = pos in sb_lower
            sb_has_neg = neg in sb_lower

            # Direct contradiction
            if (fb_has_pos and sb_has_neg) or (fb_has_neg and sb_has_pos):
                conflict = ConflictObject(
                    conflict_id=str(uuid4()),
                    claim_a=first_brain_answer[:500],
                    claim_b=second_brain_answer[:500],
                    source_a="First Brain",
                    source_b="Second Brain",
                    severity=ConflictSeverity.HIGH,
                    question_context=question,
                    metadata={"negation_pair": (pos, neg)},
                )
                self._conflicts[conflict.conflict_id] = conflict
                conflicts.append(conflict)

        # Check for numerical contradictions
        fb_numbers = self._extract_numbers(first_brain_answer)
        sb_numbers = self._extract_numbers(second_brain_answer)

        for fb_num in fb_numbers:
            for sb_num in sb_numbers:
                if fb_num != sb_num and abs(fb_num - sb_num) / max(abs(fb_num), abs(sb_num)) > 0.1:
                    conflict = ConflictObject(
                        conflict_id=str(uuid4()),
                        claim_a=first_brain_answer[:500],
                        claim_b=second_brain_answer[:500],
                        source_a="First Brain",
                        source_b="Second Brain",
                        severity=ConflictSeverity.MEDIUM,
                        question_context=question,
                        metadata={"numerical_discrepancy": {"first": fb_num, "second": sb_num}},
                    )
                    self._conflicts[conflict.conflict_id] = conflict
                    conflicts.append(conflict)

        return [asdict(c) for c in conflicts]

    def _extract_numbers(self, text: str) -> list[float]:
        """Extract numbers from text."""
        import re
        numbers = []
        for match in re.finditer(r"[-+]?\d*\.?\d+", text):
            try:
                numbers.append(float(match.group()))
            except ValueError:
                pass
        return numbers

    def investigate(self, conflict_id: str, evidence_a: list[str], evidence_b: list[str]) -> dict[str, Any]:
        """Add evidence and investigate a conflict."""
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return {"success": False, "error": "Conflict not found"}

        conflict.evidence_a = evidence_a
        conflict.evidence_b = evidence_b
        conflict.status = ConflictStatus.INVESTIGATING

        return {"success": True, "conflict_id": conflict_id, "status": conflict.status.value}

    def resolve(
        self,
        conflict_id: str,
        resolution: str,
        confidence: float,
        resolved_by: str = "mid-brain",
    ) -> dict[str, Any]:
        """Resolve a conflict with a reasoned decision."""
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return {"success": False, "error": "Conflict not found"}

        conflict.resolution = resolution
        conflict.confidence = confidence
        conflict.status = ConflictStatus.RESOLVED
        conflict.resolved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conflict.metadata["resolved_by"] = resolved_by

        return {
            "success": True,
            "conflict_id": conflict_id,
            "resolution": resolution,
            "confidence": confidence,
        }

    def accept_uncertain(self, conflict_id: str, reason: str) -> dict[str, Any]:
        """Mark conflict as accepted uncertainty when resolution not possible."""
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return {"success": False, "error": "Conflict not found"}

        conflict.status = ConflictStatus.ACCEPTED_AS_UNCERTAIN
        conflict.resolution = f"Accepted as uncertain: {reason}"
        conflict.resolved_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        conflict.metadata["uncertainty_reason"] = reason

        return {"success": True, "conflict_id": conflict_id, "status": conflict.status.value}

    def get_conflict(self, conflict_id: str) -> ConflictObject | None:
        """Get a conflict by ID."""
        return self._conflicts.get(conflict_id)

    def list_conflicts(self, status: ConflictStatus | None = None) -> list[dict[str, Any]]:
        """List all conflicts, optionally filtered by status."""
        conflicts = list(self._conflicts.values())
        if status:
            conflicts = [c for c in conflicts if c.status == status]
        return [c.__dict__ for c in conflicts]

    def get_open_conflicts(self) -> list[dict[str, Any]]:
        """Get all open conflicts."""
        return self.list_conflicts(ConflictStatus.OPEN)
