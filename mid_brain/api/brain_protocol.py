"""Brain Communication Protocol - Message types and schemas for inter-brain communication."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class MessageType(str, Enum):
    """Types of messages between brains."""
    QUESTION = "question"
    ANSWER = "answer"
    REQUEST_EVIDENCE = "request_evidence"
    CHALLENGE = "challenge"
    VERIFY = "verify"
    COMPARE = "compare"
    SYNTHESIZE = "synthesize"
    LEARN = "learn"
    REFLECT = "reflect"
    RECALL = "recall"
    CONFLICT = "conflict"
    PROMOTE = "promote"
    REJECT = "reject"
    HEARTBEAT = "heartbeat"
    ERROR = "error"


class MessagePriority(int, Enum):
    """Message priority levels."""
    LOW = 0
    NORMAL = 50
    HIGH = 75
    CRITICAL = 100


@dataclass(slots=True)
class BrainMessage:
    """
    Base message structure for inter-brain communication.

    Every message must have:
    - message_id: Unique identifier
    - trace_id: Trace ID for request tracing
    - timestamp: Unix timestamp
    - source: Source brain identifier
    - destination: Destination brain identifier
    - type: Message type
    - payload: Message payload
    - context: Additional context
    - metadata: Additional metadata
    """
    message_id: str = field(default_factory=lambda: uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    source: str = ""
    destination: str = ""
    type: MessageType = MessageType.QUESTION
    priority: MessagePriority = MessagePriority.NORMAL
    payload: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BrainMessage:
        """Create from dictionary."""
        # Convert string enums back
        if isinstance(data.get("type"), str):
            data["type"] = MessageType(data["type"])
        if isinstance(data.get("priority"), (int, str)):
            data["priority"] = MessagePriority(int(data["priority"]))
        return cls(**data)


@dataclass(slots=True)
class BrainRequest:
    """
    Request message from one brain to another.

    Extends BrainMessage with request-specific fields.
    """
    message: BrainMessage
    timeout_seconds: float = 30.0
    retry_count: int = 0
    max_retries: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "timeout_seconds": self.timeout_seconds,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
        }


@dataclass(slots=True)
class BrainResponse:
    """
    Response message from one brain to another.

    Extends BrainMessage with response-specific fields.
    """
    message: BrainMessage
    success: bool = True
    error: str | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass(slots=True)
class BrainEvent:
    """
    Event notification between brains (async, no response expected).
    """
    message: BrainMessage
    event_type: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "event_type": self.event_type,
            "timestamp": self.timestamp,
        }


# Convenience functions for creating common message types

def create_question(
    source: str,
    destination: str,
    question: str,
    trace_id: str | None = None,
    project_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> BrainMessage:
    """Create a QUESTION message."""
    return BrainMessage(
        trace_id=trace_id or uuid4().hex,
        source=source,
        destination=destination,
        type=MessageType.QUESTION,
        payload={
            "question": question,
            "project_id": project_id,
        },
        context=context or {},
    )


def create_answer(
    source: str,
    destination: str,
    question: str,
    answer: str,
    confidence: float,
    trace_id: str,
    evidence: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> BrainMessage:
    """Create an ANSWER message."""
    return BrainMessage(
        trace_id=trace_id,
        source=source,
        destination=destination,
        type=MessageType.ANSWER,
        payload={
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "evidence": evidence or [],
        },
        metadata=metadata or {},
    )


def create_conflict(
    source: str,
    destination: str,
    claim_a: str,
    claim_b: str,
    source_a: str,
    source_b: str,
    trace_id: str,
    severity: str = "medium",
) -> BrainMessage:
    """Create a CONFLICT message."""
    return BrainMessage(
        trace_id=trace_id,
        source=source,
        destination=destination,
        type=MessageType.CONFLICT,
        priority=MessagePriority.HIGH,
        payload={
            "claim_a": claim_a,
            "claim_b": claim_b,
            "source_a": source_a,
            "source_b": source_b,
            "severity": severity,
        },
    )


def create_verify_request(
    source: str,
    destination: str,
    claim: str,
    evidence: list[str],
    trace_id: str,
) -> BrainMessage:
    """Create a VERIFY message."""
    return BrainMessage(
        trace_id=trace_id,
        source=source,
        destination=destination,
        type=MessageType.VERIFY,
        payload={
            "claim": claim,
            "evidence": evidence,
        },
    )


def create_learn_message(
    source: str,
    destination: str,
    learning_type: str,
    content: str,
    confidence: float,
    trace_id: str,
    metadata: dict[str, Any] | None = None,
) -> BrainMessage:
    """Create a LEARN message."""
    return BrainMessage(
        trace_id=trace_id,
        source=source,
        destination=destination,
        type=MessageType.LEARN,
        payload={
            "learning_type": learning_type,
            "content": content,
            "confidence": confidence,
        },
        metadata=metadata or {},
    )
