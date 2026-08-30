"""Frontmatter handling for Mid Brain Obsidian notes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class FrontmatterType(str, Enum):
    """Types of Mid Brain notes in Obsidian."""

    QUESTION = "question"
    ANSWER = "answer"
    KNOWLEDGE = "knowledge"
    EXPERIENCE = "experience"
    DECISION = "decision"
    LESSON = "lesson"
    STRATEGY = "strategy"
    CONFLICT = "conflict"
    REFLECTION = "reflection"
    TASK = "task"
    AGENT_RESULT = "agent_result"
    FEEDBACK = "feedback"
    META = "meta"


@dataclass(slots=True)
class MidBrainFrontmatter:
    """Standard frontmatter for Mid Brain Obsidian notes."""

    title: str
    type: FrontmatterType
    project: str | None = None
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    confidence: float = 0.5
    created: str = field(default_factory=lambda: datetime.now().isoformat())
    updated: str = field(default_factory=lambda: datetime.now().isoformat())
    sync_to_brain: bool = True
    trace_id: str = field(default_factory=lambda: uuid4().hex[:12])
    source_brain: str = "mid-brain"
    cognitive_phase: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    related_entities: list[str] = field(default_factory=list)
    backlinks: list[str] = field(default_factory=list)

    def to_yaml(self) -> str:
        """Convert to YAML frontmatter string."""
        import yaml

        data = {
            "title": self.title,
            "type": self.type.value,
            "project": self.project,
            "tags": self.tags,
            "importance": self.importance,
            "confidence": self.confidence,
            "created": self.created,
            "updated": self.updated,
            "sync_to_brain": self.sync_to_brain,
            "trace_id": self.trace_id,
            "source_brain": self.source_brain,
            "cognitive_phase": self.cognitive_phase,
            "provenance": self.provenance,
            "related_entities": self.related_entities,
            "backlinks": self.backlinks,
        }
        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}
        return yaml.dump(data, allow_unicode=True, sort_keys=False).strip()

    @classmethod
    def from_yaml(cls, yaml_str: str) -> MidBrainFrontmatter:
        """Parse from YAML frontmatter string."""
        import yaml

        data = yaml.safe_load(yaml_str)
        if isinstance(data.get("type"), str):
            data["type"] = FrontmatterType(data["type"])
        return cls(**data)


def parse_frontmatter(content: str) -> tuple[MidBrainFrontmatter | None, str]:
    """Parse frontmatter from markdown content.

    Returns (frontmatter, body_content).
    """
    if not content.startswith("---"):
        return None, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None, content

    try:
        fm = MidBrainFrontmatter.from_yaml(parts[1])
        body = parts[2].lstrip("\n")
        return fm, body
    except Exception:
        return None, content


def create_note(frontmatter: MidBrainFrontmatter, body: str) -> str:
    """Create a full markdown note with frontmatter."""
    return f"---\n{frontmatter.to_yaml()}\n---\n\n{body}"
