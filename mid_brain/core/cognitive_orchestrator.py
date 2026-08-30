"""Cognitive Orchestrator - Coordinates all Mid Brain components for the cognitive loop."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from mid_brain.core.mid_brain import MidBrain


@dataclass(slots=True)
class CognitiveStep:
    """A single step in the cognitive process."""
    phase: str
    input: dict[str, Any]
    output: dict[str, Any]
    duration_ms: float
    success: bool


@dataclass(slots=True)
class CognitiveResult:
    """Result of the full cognitive process."""
    question: str
    answer: str
    confidence: float
    trace_id: str
    steps: list[CognitiveStep] = field(default_factory=list)
    memories_used: int = 0
    knowledge_used: int = 0
    conflicts_detected: int = 0
    learning_stored: int = 0
    reflection_stored: int = 0
    sources: dict[str, Any] = field(default_factory=dict)
    confidence_report: Any = None
    network_nodes_created: int = 0
    obsidian_notes_synced: int = 0


class CognitiveOrchestrator:
    """
    Orchestrates the complete cognitive loop.

    Flow (Phase 5+):
    1. RECALL - Retrieve from Mid Brain memory & knowledge
    2. UNDERSTAND - Analyze question intent
    3. QUESTION - Query First Brain (experience) & Second Brain (knowledge)
    4. COMPARE - Compare answers from both brains
    5. CONFLICT DETECTION - Detect contradictions
    6. EVIDENCE - Evaluate supporting evidence
    7. CONFIDENCE - Calculate confidence score
    8. SYNTHESIS - Synthesize final answer
    9. DECISION - Determine if storage is needed
    10. REFLECTION - Reflect on the process
    11. LEARNING - Extract and store learning
    12. MEMORY - Store in Mid Brain memory
    13. ADAPTIVE NETWORK - Update knowledge graph
    14. FUTURE REFERENCE - Index for future retrieval
    """

    def __init__(self, mid_brain: MidBrain) -> None:
        self.mid_brain = mid_brain
        self._initialized = False

    def initialize(self) -> None:
        """Initialize orchestrator."""
        self._initialized = True

    def process(
        self,
        question: str,
        project_id: str | None = None,
        context: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute the full cognitive loop."""
        trace_id = trace_id or str(uuid4())
        context = context or {}
        start_time = time.time()
        steps: list[CognitiveStep] = []

        # Initialize tracking
        network_nodes_created = 0
        obsidian_notes_synced = 0
        confidence_report = None

        # Helper function to sync to Obsidian
        def _sync_to_obsidian(phase: str, cognitive_output: dict[str, Any]) -> None:
            nonlocal obsidian_notes_synced
            if not self.mid_brain.config.enable_obsidian:
                return
            try:
                from mid_brain.obsidian.note_generator import NoteContext
                note_context = NoteContext(
                    trace_id=trace_id,
                    project_id=project_id,
                    cognitive_phase=phase,
                    source_brain="mid-brain",
                    confidence=confidence_report.overall_confidence if confidence_report else 0.5,
                    importance=0.7,
                )
                result = self.mid_brain.obsidian.sync_to_obsidian(cognitive_output, note_context)
                if result.success:
                    obsidian_notes_synced += result.notes_synced
            except Exception:
                pass  # Don't let sync failures break the loop

        # Helper function to add node to adaptive network
        def _add_to_network(node_type: str, content: str, confidence: float = 0.5, importance: float = 0.5) -> None:
            nonlocal network_nodes_created
            if not self.mid_brain.config.enable_network:
                return
            try:
                self.mid_brain.network.add_node(
                    type=node_type,
                    content=content,
                    project_id=project_id,
                    confidence=confidence,
                    importance=importance,
                    metadata={"trace_id": trace_id, "question": question[:200]},
                )
                network_nodes_created += 1
            except Exception:
                pass

        # Helper function to publish feedback event
        def _publish_feedback(fb_type: str, content: str, fb_context: dict[str, Any] | None = None) -> None:
            try:
                from mid_brain.feedback.feedback_event import (
                    FeedbackEvent,
                    FeedbackSource,
                    FeedbackType,
                )
                event = FeedbackEvent(
                    source=FeedbackSource.MID_BRAIN,
                    type=FeedbackType(fb_type.upper()) if fb_type.upper() in [t.value for t in FeedbackType] else FeedbackType.OBSERVATION,
                    content=content,
                    context=fb_context or {},
                    trace_id=trace_id,
                    project_id=project_id,
                    confidence=confidence_report.overall_confidence if confidence_report else 0.5,
                )
                self.mid_brain.feedback.publish(event)
            except Exception:
                pass

        # Step 1: RECALL - Retrieve from Mid Brain memory
        step_start = time.time()
        recall_result = self.mid_brain.memory.retrieve(
            query=question,
            project_id=project_id,
            limit=10,
        )
        steps.append(CognitiveStep(
            phase="RECALL",
            input={"query": question, "project_id": project_id},
            output={"results_count": len(recall_result.get("results", []))},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("RECALL", {"question": question, "recall_results": recall_result.get("results", [])})

        # Step 2: UNDERSTAND - Analyze question (placeholder for now)
        step_start = time.time()
        understanding = self._analyze_question(question)
        steps.append(CognitiveStep(
            phase="UNDERSTAND",
            input={"question": question},
            output=understanding,
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("UNDERSTAND", {"question": question, "understanding": understanding})
        _add_to_network("question", question, confidence=0.8, importance=0.8)

        # Step 3: QUESTION - Query First Brain & Second Brain
        step_start = time.time()
        first_brain_answer = self._query_first_brain(question, project_id, context)
        second_brain_answer = self._query_second_brain(question, project_id, context)
        steps.append(CognitiveStep(
            phase="QUESTION",
            input={"question": question},
            output={
                "first_brain": first_brain_answer is not None,
                "second_brain": second_brain_answer is not None,
            },
            duration_ms=(time.time() - step_start) * 1000,
            success=first_brain_answer is not None or second_brain_answer is not None,
        ))
        _sync_to_obsidian("QUESTION", {
            "question": question,
            "first_brain_answer": first_brain_answer,
            "second_brain_answer": second_brain_answer,
        })

        # Step 4: COMPARE - Compare answers
        step_start = time.time()
        comparison = self.mid_brain.reasoning.compare_answers(
            first_brain_answer,
            second_brain_answer,
            question,
        )
        steps.append(CognitiveStep(
            phase="COMPARE",
            input={"first_brain": first_brain_answer, "second_brain": second_brain_answer},
            output=comparison,
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("COMPARE", {"comparison": comparison})

        # Step 5: CONFLICT DETECTION
        step_start = time.time()
        conflicts = []
        if self.mid_brain.config.enable_conflict_detection:
            conflicts = self.mid_brain.conflict.detect(
                first_brain_answer,
                second_brain_answer,
                question,
            )
        steps.append(CognitiveStep(
            phase="CONFLICT_DETECTION",
            input={"first_brain": first_brain_answer, "second_brain": second_brain_answer},
            output={"conflicts_count": len(conflicts)},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        # Sync conflicts to Obsidian
        if conflicts:
            for conflict in conflicts:
                _sync_to_obsidian("CONFLICT_DETECTION", {
                    "claim_a": conflict.get("claim_a", ""),
                    "claim_b": conflict.get("claim_b", ""),
                    "severity": conflict.get("severity", "medium"),
                    "evidence_a": conflict.get("evidence_a", []),
                    "evidence_b": conflict.get("evidence_b", []),
                    "resolution": conflict.get("resolution"),
                })
                _publish_feedback("CONFLICT", f"Conflict: {conflict.get('claim_a')} vs {conflict.get('claim_b')}", conflict)

        # Step 6: EVIDENCE - Evaluate evidence
        step_start = time.time()
        evidence = self.mid_brain.reasoning.evaluate_evidence(
            first_brain_answer,
            second_brain_answer,
            recall_result,
            conflicts,
        )
        steps.append(CognitiveStep(
            phase="EVIDENCE",
            input={},
            output=evidence,
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("EVIDENCE", {"evidence": evidence})

        # Step 7: CONFIDENCE - Calculate confidence using new ConfidenceEngine
        step_start = time.time()
        if self.mid_brain.config.enable_confidence:
            confidence_report = self.mid_brain.confidence.calculate(
                evidence=evidence,
                conflicts=conflicts,
                first_brain_answer=first_brain_answer,
                second_brain_answer=second_brain_answer,
                mid_brain_memories=recall_result.get("results", []),
                human_confirmed=False,
            )
            confidence = confidence_report.overall_confidence
        else:
            confidence = self.mid_brain.reasoning.calculate_confidence(
                evidence,
                conflicts,
                first_brain_answer,
                second_brain_answer,
            )
        steps.append(CognitiveStep(
            phase="CONFIDENCE",
            input=evidence,
            output={"confidence": confidence, "level": confidence_report.level if confidence_report else "UNKNOWN"},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("CONFIDENCE", {
            "confidence": confidence,
            "level": confidence_report.level if confidence_report else "UNKNOWN",
            "factors": [{"name": f.name, "score": f.score, "explanation": f.explanation} for f in confidence_report.factors] if confidence_report else [],
            "limitations": confidence_report.limitations if confidence_report else [],
            "recommendations": confidence_report.recommendations if confidence_report else [],
        })
        _add_to_network("confidence", f"Confidence {confidence:.2f} for: {question[:100]}", confidence=confidence)

        # Step 8: SYNTHESIS - Synthesize answer
        step_start = time.time()
        synthesis = self.mid_brain.reasoning.synthesize(
            question,
            first_brain_answer,
            second_brain_answer,
            comparison,
            evidence,
            confidence,
        )
        answer = synthesis.get("answer", "")
        steps.append(CognitiveStep(
            phase="SYNTHESIS",
            input={},
            output={"answer_length": len(answer), "sources": synthesis.get("sources_used", [])},
            duration_ms=(time.time() - step_start) * 1000,
            success=bool(answer),
        ))
        _sync_to_obsidian("SYNTHESIS", {
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "sources": {"first_brain": first_brain_answer, "second_brain": second_brain_answer},
        })
        _add_to_network("answer", answer, confidence=confidence, importance=0.8)

        # Step 9: DECISION - Determine storage
        step_start = time.time()
        should_store = self._should_store(answer, confidence, question)
        steps.append(CognitiveStep(
            phase="DECISION",
            input={"confidence": confidence},
            output={"should_store": should_store},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))

        # Step 10: REFLECTION - Reflect on process
        step_start = time.time()
        reflection_stored = 0
        if self.mid_brain.config.enable_reflection and should_store:
            reflection_result = self.mid_brain.reflection.reflect(
                question=question,
                answer=answer,
                confidence=confidence,
                steps=steps,
                project_id=project_id,
            )
            reflection_stored = 1 if reflection_result.get("stored") else 0
            if reflection_result.get("stored"):
                _add_to_network("reflection", reflection_result.get("content", "")[:500], confidence=confidence)
        steps.append(CognitiveStep(
            phase="REFLECTION",
            input={"should_store": should_store},
            output={"stored": reflection_stored > 0, "reflection_id": reflection_result.get("reflection_id") if 'reflection_result' in locals() else None},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("REFLECTION", {
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "reflection": reflection_result if 'reflection_result' in locals() else {},
        })

        # Step 11: LEARNING - Extract learning
        step_start = time.time()
        learning_stored = 0
        if self.mid_brain.config.enable_learning and should_store:
            learning_result = self.mid_brain.learning.extract_learning(
                question=question,
                answer=answer,
                confidence=confidence,
                project_id=project_id,
            )
            learning_stored = learning_result.get("stored_count", 0)
            for item in learning_result.get("items", []):
                _add_to_network("lesson", item.get("content", "")[:500], confidence=item.get("confidence", 0.7))
        steps.append(CognitiveStep(
            phase="LEARNING",
            input={"should_store": should_store},
            output={"stored_count": learning_stored, "items": learning_result.get("items", []) if 'learning_result' in locals() else []},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))
        _sync_to_obsidian("LEARNING", {"items": learning_result.get("items", []) if 'learning_result' in locals() else []})

        # Step 12: MEMORY - Store in Mid Brain memory
        step_start = time.time()
        memory_stored = 0
        if should_store:
            memory_result = self.mid_brain.memory.store(
                content=answer,
                question=question,
                project_id=project_id,
                confidence=confidence,
                trace_id=trace_id,
            )
            memory_stored = 1 if memory_result.get("stored") else 0
            if memory_result.get("stored"):
                _add_to_network("memory", answer[:500], confidence=confidence, importance=0.7)
        steps.append(CognitiveStep(
            phase="MEMORY",
            input={"should_store": should_store},
            output={"stored": memory_stored > 0, "memory_id": memory_result.get("memory_id") if 'memory_result' in locals() else None},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))

        # Step 13: ADAPTIVE NETWORK - Update knowledge graph
        step_start = time.time()
        if self.mid_brain.config.enable_network and should_store:
            # Link answer to question
            try:
                question_node = self.mid_brain.network.search_nodes(question, project_id=project_id, limit=1)
                if question_node:
                    answer_nodes = self.mid_brain.network.search_nodes(answer[:100], project_id=project_id, limit=1)
                    if answer_nodes:
                        self.mid_brain.network.add_edge(
                            question_node[0].node_id,
                            answer_nodes[0].node_id,
                            "derived_from",
                            weight=confidence,
                            confidence=confidence,
                        )
            except Exception:
                pass
        steps.append(CognitiveStep(
            phase="ADAPTIVE_NETWORK",
            input={"should_store": should_store, "confidence": confidence},
            output={"nodes_created": network_nodes_created},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))

        # Step 14: FUTURE REFERENCE - Index for future retrieval
        step_start = time.time()
        if self.mid_brain.config.enable_reference and should_store:
            self.mid_brain.reference.index(
                question=question,
                answer=answer,
                confidence=confidence,
                trace_id=trace_id,
                project_id=project_id,
            )
        steps.append(CognitiveStep(
            phase="FUTURE_REFERENCE",
            input={"should_store": should_store},
            output={"indexed": should_store},
            duration_ms=(time.time() - step_start) * 1000,
            success=True,
        ))

        total_duration = (time.time() - start_time) * 1000

        # Publish final feedback event
        _publish_feedback("ANSWER", f"Answered: {question[:100]} -> {answer[:200]}", {
            "confidence": confidence,
            "trace_id": trace_id,
            "conflicts": len(conflicts),
        })

        return {
            "question": question,
            "answer": answer,
            "confidence": confidence,
            "trace_id": trace_id,
            "total_duration_ms": total_duration,
            "steps": [asdict(s) for s in steps],
            "memories_used": len(recall_result.get("results", [])),
            "knowledge_used": 0,
            "conflicts_detected": len(conflicts),
            "learning_stored": learning_stored,
            "reflection_stored": reflection_stored,
            "sources": {
                "first_brain": first_brain_answer,
                "second_brain": second_brain_answer,
                "mid_brain_memory": recall_result,
            },
            "confidence_report": {
                "level": confidence_report.level,
                "methodology": confidence_report.methodology,
                "limitations": confidence_report.limitations,
                "recommendations": confidence_report.recommendations,
                "factors": [{"name": f.name, "weight": f.weight, "score": f.score, "explanation": f.explanation} for f in confidence_report.factors],
            } if confidence_report else None,
            "network_nodes_created": network_nodes_created,
            "obsidian_notes_synced": obsidian_notes_synced,
        }

    # ------------------------------------------------------------------ helpers

    def _analyze_question(self, question: str) -> dict[str, Any]:
        """Analyze question intent (placeholder for future NLP)."""
        return {
            "type": "factual" if "?" in question else "statement",
            "complexity": "simple",
            "entities": [],
        }

    def _query_first_brain(
        self,
        question: str,
        project_id: str | None,
        context: dict[str, Any],
    ) -> str | None:
        """Query First Brain (Experience) via adapter."""
        try:
            response = self.mid_brain.first_brain.ask(
                question=question,
                project_id=project_id,
                trace_id=context.get("trace_id"),
                context=context,
            )
            if response.success and response.message:
                return response.message.payload.get("answer")
        except Exception:
            pass
        return None

    def _query_second_brain(
        self,
        question: str,
        project_id: str | None,
        context: dict[str, Any],
    ) -> str | None:
        """Query Second Brain (Knowledge) via adapter."""
        try:
            response = self.mid_brain.second_brain.search(
                query=question,
                project_id=project_id,
                top_k=8,
            )
            if response.success and response.message:
                return response.message.payload.get("answer")
        except Exception:
            pass
        return None

    def _should_store(self, answer: str, confidence: float, question: str) -> bool:
        """Determine if result should be stored."""
        return not (not answer or confidence < self.mid_brain.config.confidence_threshold)
