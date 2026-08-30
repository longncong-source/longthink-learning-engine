"""Feedback Event schema for Mid Brain - Inter-brain and human communication."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class FeedbackType(str, Enum):
    """Types of feedback events."""

    OBSERVATION = "observation"
    KNOWLEDGE = "knowledge"
    ANSWER = "answer"
    QUESTION = "question"
    EVIDENCE = "evidence"
    DECISION = "decision"
    CONFLICT = "conflict"
    LEARNING = "learning"
    LESSON = "lesson"
    AGENT_RESULT = "agent_result"
    ERROR = "error"
    HUMAN_FEEDBACK = "human_feedback"


class FeedbackSource(str, Enum):
    """Source of feedback."""

    FIRST_BRAIN = "first_brain"
    SECOND_BRAIN = "second_brain"
    MID_BRAIN = "mid_brain"
    AGENT_CORE = "agent_core"
    HUMAN = "human"
    SYSTEM = "system"


@dataclass(slots=True)
class FeedbackEvent:
    """Standard feedback event for inter-brain and human communication."""

    feedback_id: str = field(default_factory=lambda: uuid4().hex[:12])
    source: FeedbackSource = FeedbackSource.MID_BRAIN
    destination: FeedbackSource | None = None
    type: FeedbackType = FeedbackType.OBSERVATION
    content: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    confidence: float = 0.5
    provenance: dict[str, Any] = field(default_factory=dict)
    related_task: str | None = None
    related_knowledge: str | None = None
    trace_id: str | None = None
    project_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "source": self.source.value,
            "destination": self.destination.value if self.destination else None,
            "type": self.type.value,
            "content": self.content,
            "context": self.context,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "related_task": self.related_task,
            "related_knowledge": self.related_knowledge,
            "trace_id": self.trace_id,
            "project_id": self.project_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeedbackEvent:
        return cls(
            feedback_id=data.get("feedback_id", uuid4().hex[:12]),
            source=FeedbackSource(data["source"]) if data.get("source") else FeedbackSource.MID_BRAIN,
            destination=FeedbackSource(data["destination"]) if data.get("destination") else None,
            type=FeedbackType(data["type"]) if data.get("type") else FeedbackType.OBSERVATION,
            content=data.get("content", ""),
            context=data.get("context", {}),
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            confidence=data.get("confidence", 0.5),
            provenance=data.get("provenance", {}),
            related_task=data.get("related_task"),
            related_knowledge=data.get("related_knowledge"),
            trace_id=data.get("trace_id"),
            project_id=data.get("project_id"),
        )


class FeedbackBus:
    """Simple in-memory feedback bus for inter-component communication."""

    def __init__(self) -> None:
        self._subscribers: dict[FeedbackType, list[callable]] = {}
        self._history: list[FeedbackEvent] = []
        self._max_history = 10000

    def subscribe(self, feedback_type: FeedbackType, callback: callable) -> None:
        """Subscribe to feedback events of a specific type."""
        if feedback_type not in self._subscribers:
            self._subscribers[feedback_type] = []
        self._subscribers[feedback_type].append(callback)

    def unsubscribe(self, feedback_type: FeedbackType, callback: callable) -> bool:
        """Unsubscribe from feedback events."""
        if feedback_type in self._subscribers:
            try:
                self._subscribers[feedback_type].remove(callback)
                return True
            except ValueError:
                return False
        return False

    def publish(self, event: FeedbackEvent) -> None:
        """Publish a feedback event to all subscribers."""
        # Store in history
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Notify subscribers
        callbacks = self._subscribers.get(event.type, [])
        for callback in callbacks:
            try:
                callback(event)
            except Exception:
                pass  # Don't let subscriber errors break the bus

    def get_history(
        self,
        feedback_type: FeedbackType | None = None,
        source: FeedbackSource | None = None,
        limit: int = 100,
    ) -> list[FeedbackEvent]:
        """Get recent feedback history."""
        events = self._history

        if feedback_type:
            events = [e for e in events if e.type == feedback_type]
        if source:
            events = [e for e in events if e.source == source]

        return events[-limit:]

    def clear_history(self) -> None:
        """Clear feedback history."""
        self._history.clear()


# Global feedback bus instance
_feedback_bus: FeedbackBus | None = None


def get_feedback_bus() -> FeedbackBus:
    """Get or create global feedback bus."""
    global _feedback_bus
    if _feedback_bus is None:
        _feedback_bus = FeedbackBus()
    return _feedback_bus
