"""Vault management for Mid Brain Obsidian integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VaultStructure:
    """Standard Mid Brain vault folder structure."""

    root: Path
    inbox: Path = field(init=False)
    questions: Path = field(init=False)
    thinking: Path = field(init=False)
    knowledge: Path = field(init=False)
    experiences: Path = field(init=False)
    decisions: Path = field(init=False)
    lessons: Path = field(init=False)
    strategies: Path = field(init=False)
    projects: Path = field(init=False)
    conflicts: Path = field(init=False)
    references: Path = field(init=False)
    agent: Path = field(init=False)
    feedback: Path = field(init=False)
    meta: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "inbox", self.root / "00_Inbox")
        object.__setattr__(self, "questions", self.root / "01_Questions")
        object.__setattr__(self, "thinking", self.root / "02_Thinking")
        object.__setattr__(self, "knowledge", self.root / "03_Knowledge")
        object.__setattr__(self, "experiences", self.root / "04_Experiences")
        object.__setattr__(self, "decisions", self.root / "05_Decisions")
        object.__setattr__(self, "lessons", self.root / "06_Lessons")
        object.__setattr__(self, "strategies", self.root / "07_Strategies")
        object.__setattr__(self, "projects", self.root / "08_Projects")
        object.__setattr__(self, "conflicts", self.root / "09_Conflicts")
        object.__setattr__(self, "references", self.root / "10_References")
        object.__setattr__(self, "agent", self.root / "11_Agent")
        object.__setattr__(self, "feedback", self.root / "12_Feedback")
        object.__setattr__(self, "meta", self.root / "13_Meta")

    def all_folders(self) -> list[Path]:
        """Get all folder paths."""
        return [
            self.inbox,
            self.questions,
            self.thinking,
            self.knowledge,
            self.experiences,
            self.decisions,
            self.lessons,
            self.strategies,
            self.projects,
            self.conflicts,
            self.references,
            self.agent,
            self.feedback,
            self.meta,
        ]

    def folder_for_type(self, note_type: str) -> Path:
        """Map note type to folder."""
        mapping = {
            "question": self.questions,
            "answer": self.knowledge,
            "knowledge": self.knowledge,
            "experience": self.experiences,
            "decision": self.decisions,
            "lesson": self.lessons,
            "strategy": self.strategies,
            "conflict": self.conflicts,
            "reflection": self.thinking,
            "task": self.agent,
            "agent_result": self.agent,
            "feedback": self.feedback,
            "meta": self.meta,
        }
        return mapping.get(note_type, self.inbox)


class VaultManager:
    """Manages Mid Brain Obsidian vault operations."""

    def __init__(self, vault_path: str | Path) -> None:
        self.root = Path(vault_path).resolve()
        self.structure = VaultStructure(self.root)

    def initialize(self) -> None:
        """Create vault folder structure."""
        for folder in self.structure.all_folders():
            folder.mkdir(parents=True, exist_ok=True)
        # Create .obsidian folder for workspace config
        (self.root / ".obsidian").mkdir(exist_ok=True)

    def get_note_path(self, frontmatter_type: str, title: str, project: str | None = None) -> Path:
        """Determine the file path for a note."""
        folder = self.structure.folder_for_type(frontmatter_type)
        if project:
            folder = folder / project
            folder.mkdir(parents=True, exist_ok=True)
        # Sanitize title for filename
        safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)
        safe_title = safe_title[:100]  # Limit length
        return folder / f"{safe_title}.md"

    def write_note(self, path: Path, content: str) -> None:
        """Write note to vault."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def read_note(self, path: Path) -> str | None:
        """Read note from vault."""
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_notes(self, folder: Path | None = None, pattern: str = "*.md") -> list[Path]:
        """List notes in vault."""
        target = folder or self.root
        return list(target.rglob(pattern))

    def find_notes_by_tag(self, tag: str, folder: Path | None = None) -> list[Path]:
        """Find notes containing a specific tag."""
        import yaml

        target = folder or self.root
        results = []
        for note_path in target.rglob("*.md"):
            try:
                content = note_path.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        fm = yaml.safe_load(parts[1])
                        tags = fm.get("tags", [])
                        if tag in tags:
                            results.append(note_path)
            except Exception:
                continue
        return results

    def find_notes_by_trace_id(self, trace_id: str) -> list[Path]:
        """Find notes by trace_id."""
        import yaml

        results = []
        for note_path in self.root.rglob("*.md"):
            try:
                content = note_path.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        fm = yaml.safe_load(parts[1])
                        if fm.get("trace_id") == trace_id:
                            results.append(note_path)
            except Exception:
                continue
        return results

    def update_frontmatter(self, path: Path, updates: dict[str, Any]) -> bool:
        """Update frontmatter fields in a note."""
        import yaml

        content = self.read_note(path)
        if not content or not content.startswith("---"):
            return False

        parts = content.split("---", 2)
        if len(parts) < 3:
            return False

        try:
            fm = yaml.safe_load(parts[1])
            fm.update(updates)
            fm["updated"] = __import__("datetime").datetime.now().isoformat()
            new_frontmatter = yaml.dump(fm, allow_unicode=True, sort_keys=False).strip()
            new_content = f"---\n{new_frontmatter}\n---\n\n{parts[2].lstrip()}"
            self.write_note(path, new_content)
            return True
        except Exception:
            return False
