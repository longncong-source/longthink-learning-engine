"""Sync manager for Mid Brain Obsidian integration."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mid_brain.obsidian.frontmatter import MidBrainFrontmatter, parse_frontmatter
from mid_brain.obsidian.note_generator import NoteContext, NoteGenerator
from mid_brain.obsidian.vault_manager import VaultManager


@dataclass(slots=True)
class SyncResult:
    """Result of a sync operation."""

    success: bool
    notes_synced: int = 0
    notes_updated: int = 0
    notes_failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


class SyncManager:
    """Manages bidirectional sync between Mid Brain and Obsidian vault."""

    def __init__(
        self,
        vault_path: str | Path,
        mid_brain: Any = None,
    ) -> None:
        self.vault = VaultManager(vault_path)
        self.generator = NoteGenerator(self.vault)
        self.mid_brain = mid_brain
        self._last_sync_time: float | None = None

    def initialize(self) -> None:
        """Initialize vault structure."""
        self.vault.initialize()

    def sync_to_obsidian(
        self,
        cognitive_output: dict[str, Any],
        context: NoteContext,
    ) -> SyncResult:
        """Sync Mid Brain cognitive output to Obsidian."""
        start = time.time()
        result = SyncResult(success=True)

        try:
            phase = context.cognitive_phase or "UNKNOWN"

            if phase == "UNDERSTAND":
                note = self.generator.generate_question_note(
                    cognitive_output.get("question", ""),
                    context,
                    cognitive_output.get("understanding"),
                )
            elif phase == "SYNTHESIS":
                note = self.generator.generate_answer_note(
                    cognitive_output.get("question", ""),
                    cognitive_output.get("answer", ""),
                    context,
                    cognitive_output.get("confidence", 0.5),
                    cognitive_output.get("sources", {}),
                )
            elif phase == "KNOWLEDGE":
                note = self.generator.generate_knowledge_note(
                    cognitive_output.get("content", ""),
                    cognitive_output.get("kind", "fact"),
                    context,
                    cognitive_output.get("knowledge_id"),
                    cognitive_output.get("version", 1),
                    cognitive_output.get("status", "candidate"),
                )
            elif phase == "CONFLICT_DETECTION":
                note = self.generator.generate_conflict_note(
                    cognitive_output.get("claim_a", ""),
                    cognitive_output.get("claim_b", ""),
                    context,
                    cognitive_output.get("evidence_a"),
                    cognitive_output.get("evidence_b"),
                    cognitive_output.get("severity", "medium"),
                    cognitive_output.get("resolution"),
                )
            elif phase == "REFLECTION":
                note = self.generator.generate_reflection_note(
                    cognitive_output.get("question", ""),
                    cognitive_output.get("answer", ""),
                    cognitive_output.get("reflection", {}),
                    context,
                )
            elif phase == "LEARNING":
                note = self.generator.generate_learning_note(
                    cognitive_output.get("items", []),
                    context,
                )
            elif phase == "PLANNING":
                note = self.generator.generate_task_note(
                    cognitive_output.get("task_spec", {}),
                    context,
                )
            elif phase == "EXECUTION":
                note = self.generator.generate_agent_result_note(
                    cognitive_output.get("task_spec", {}),
                    cognitive_output.get("result", {}),
                    context,
                )
            elif phase == "HUMAN_FEEDBACK":
                note = self.generator.generate_feedback_note(
                    cognitive_output.get("feedback", {}),
                    context,
                )
            else:
                result.success = False
                result.errors.append(f"Unknown phase: {phase}")
                return result

            # Determine file path
            path = self.vault.get_note_path(
                context.cognitive_phase.lower() if context.cognitive_phase else "unknown",
                context.trace_id[:50],
                context.project_id,
            )

            # Write note
            self.vault.write_note(path, note)
            result.notes_synced = 1

        except Exception as e:
            result.success = False
            result.notes_failed = 1
            result.errors.append(str(e))

        result.duration_ms = (time.time() - start) * 1000
        return result

    def sync_from_obsidian(
        self,
        folder: Path | None = None,
        since: float | None = None,
    ) -> SyncResult:
        """Sync human-edited notes from Obsidian back to Mid Brain."""
        start = time.time()
        result = SyncResult(success=True)
        target = folder or self.vault.root

        try:
            for note_path in target.rglob("*.md"):
                if since and note_path.stat().st_mtime < since:
                    continue

                content = note_path.read_text(encoding="utf-8")
                fm, body = parse_frontmatter(content)

                if not fm or not fm.sync_to_brain:
                    continue

                # Process based on type
                if self.mid_brain and fm.type.value in ("knowledge", "decision", "lesson", "strategy", "experience"):
                    self._sync_knowledge_to_mid_brain(fm, body, note_path, result)
                elif self.mid_brain and fm.type.value == "feedback":
                    self._sync_feedback_to_mid_brain(fm, body, note_path, result)

        except Exception as e:
            result.success = False
            result.errors.append(str(e))

        result.duration_ms = (time.time() - start) * 1000
        return result

    def _sync_knowledge_to_mid_brain(
        self,
        fm: MidBrainFrontmatter,
        body: str,
        path: Path,
        result: SyncResult,
    ) -> None:
        """Sync knowledge note to Mid Brain knowledge manager."""
        try:
            kb_result = self.mid_brain.store_knowledge(
                content=body[:5000],  # Limit content
                kind=fm.type.value,
                importance=fm.importance,
                confidence=fm.confidence,
                source=fm.source_brain,
                project_id=fm.project,
            )
            if kb_result.get("created"):
                result.notes_synced += 1
                # Update note with knowledge_id
                self.vault.update_frontmatter(path, {"provenance.knowledge_id": kb_result.get("knowledge_id")})
            else:
                result.notes_failed += 1
        except Exception as e:
            result.notes_failed += 1
            result.errors.append(f"Knowledge sync failed for {path.name}: {e}")

    def _sync_feedback_to_mid_brain(
        self,
        fm: MidBrainFrontmatter,
        body: str,
        path: Path,
        result: SyncResult,
    ) -> None:
        """Sync feedback note to Mid Brain."""
        try:
            # Store as memory with feedback type
            mem_result = self.mid_brain.memory.store(
                content=body,
                question=f"Feedback: {fm.title}",
                memory_type="meta",
                project_id=fm.project,
                confidence=fm.confidence,
                importance=fm.importance,
                trace_id=fm.trace_id,
            )
            if mem_result.get("stored"):
                result.notes_synced += 1
            else:
                result.notes_failed += 1
        except Exception as e:
            result.notes_failed += 1
            result.errors.append(f"Feedback sync failed for {path.name}: {e}")

    def full_sync(self, context: NoteContext | None = None) -> SyncResult:
        """Perform full bidirectional sync."""
        self.initialize()
        pull_result = self.sync_from_obsidian(since=self._last_sync_time)

        self._last_sync_time = time.time()
        return pull_result

    def get_vault_stats(self) -> dict[str, Any]:
        """Get vault statistics."""
        stats = {"folders": {}, "total_notes": 0, "by_type": {}}

        for folder in self.vault.structure.all_folders():
            notes = self.vault.list_notes(folder)
            stats["folders"][folder.name] = len(notes)
            stats["total_notes"] += len(notes)

        # Count by type from frontmatter
        import yaml

        for note_path in self.vault.root.rglob("*.md"):
            try:
                content = note_path.read_text(encoding="utf-8")
                if content.startswith("---"):
                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        fm = yaml.safe_load(parts[1])
                        note_type = fm.get("type", "unknown")
                        stats["by_type"][note_type] = stats["by_type"].get(note_type, 0) + 1
            except Exception:
                continue

        return stats
