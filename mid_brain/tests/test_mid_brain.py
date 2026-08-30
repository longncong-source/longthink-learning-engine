"""Tests for Mid Brain core components."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest

from mid_brain.conflict.conflict_engine import ConflictEngine, ConflictSeverity
from mid_brain.core.mid_brain import MidBrain, MidBrainConfig
from mid_brain.knowledge.knowledge_manager import KnowledgeManager, KnowledgeStatus, KnowledgeType
from mid_brain.learning.learning_engine import LearningEngine, LearningType
from mid_brain.memory.memory_manager import MemoryManager
from mid_brain.reasoning.reasoning_engine import ReasoningEngine
from mid_brain.reference.reference_engine import ReferenceEngine
from mid_brain.reflection.reflection_engine import ReflectionEngine


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test databases."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mid_brain(temp_dir):
    """Create a MidBrain instance with test config."""
    config = MidBrainConfig(
        first_brain_url="http://test",
        second_brain_url="http://test",
        enable_reflection=True,
        enable_learning=True,
        enable_conflict_detection=True,
        enable_reference=True,
    )
    brain = MidBrain(config)
    # Override database paths to use temp dir
    brain._memory_manager = MemoryManager(str(temp_dir / "memory.db"))
    brain._knowledge_manager = KnowledgeManager(brain, str(temp_dir / "knowledge.db"))
    brain._reasoning_engine = ReasoningEngine(brain)
    brain._learning_engine = LearningEngine(brain, str(temp_dir / "learning.db"))
    brain._conflict_engine = ConflictEngine(brain)
    brain._reference_engine = ReferenceEngine(brain, str(temp_dir / "reference.db"))
    brain._reflection_engine = ReflectionEngine(brain, str(temp_dir / "reflection.db"))
    brain.initialize()
    yield brain
    brain.shutdown()


class TestMidBrainCore:
    """Tests for Mid Brain core."""

    def test_mid_brain_initialization(self, mid_brain):
        """Test Mid Brain initializes correctly."""
        assert mid_brain._initialized is True
        health = mid_brain.health()
        assert health["status"] == "healthy"
        assert health["components"]["memory"] is True
        assert health["components"]["knowledge"] is True
        assert health["components"]["reasoning"] is True
        assert health["components"]["conflict"] is True
        assert health["components"]["reference"] is True
        assert health["components"]["reflection"] is True
        assert health["components"]["learning"] is True
        assert health["components"]["orchestrator"] is True

    def test_mid_brain_status(self, mid_brain):
        """Test Mid Brain status."""
        status = mid_brain.status()
        assert status.initialized is True
        assert status.uptime_seconds > 0


class TestMemoryManager:
    """Tests for Memory Manager."""

    def test_memory_store_and_retrieve(self, temp_dir):
        """Test storing and retrieving memories."""
        mm = MemoryManager(str(temp_dir / "test_memory.db"))
        mm.initialize()

        # Store a memory
        result = mm.store(
            content="Test memory content",
            question="What is test?",
            memory_type="semantic",
            project_id="proj-1",
            confidence=0.8,
            importance=0.7,
        )
        assert result["stored"] is True
        memory_id = result["memory_id"]

        # Retrieve it
        retrieved = mm.get(memory_id)
        assert retrieved is not None
        assert retrieved.content == "Test memory content"
        assert retrieved.question == "What is test?"
        assert retrieved.memory_type == "semantic"
        assert retrieved.confidence == 0.8
        assert retrieved.importance == 0.7

    def test_memory_search(self, temp_dir):
        """Test memory search."""
        mm = MemoryManager(str(temp_dir / "test_memory2.db"))
        mm.initialize()

        mm.store(content="Python programming language", question="What is Python?", memory_type="semantic")
        mm.store(content="Java programming language", question="What is Java?", memory_type="semantic")
        mm.store(content="Python snake", question="What is a python snake?", memory_type="episodic")

        results = mm.retrieve("Python", limit=10)
        assert results["total"] >= 1
        assert any("Python" in r["content"] for r in results["results"])

    def test_memory_types(self, temp_dir):
        """Test different memory types."""
        mm = MemoryManager(str(temp_dir / "test_memory3.db"))
        mm.initialize()

        for mtype in ["working", "episodic", "semantic", "procedural", "strategic", "meta"]:
            result = mm.store(content=f"Test {mtype}", memory_type=mtype)
            assert result["stored"] is True

        stats = mm.get_stats()
        assert stats["total_memories"] == 6
        for mtype in ["working", "episodic", "semantic", "procedural", "strategic", "meta"]:
            assert stats["by_type"][mtype] == 1

    def test_memory_link(self, temp_dir):
        """Test memory linking."""
        mm = MemoryManager(str(temp_dir / "test_memory4.db"))
        mm.initialize()

        r1 = mm.store(content="Memory 1")
        r2 = mm.store(content="Memory 2")

        linked = mm.link(r1["memory_id"], r2["memory_id"], "related", 0.9)
        assert linked is True

        links = mm.get_links(r1["memory_id"])
        assert len(links) == 1
        assert links[0]["target_id"] == r2["memory_id"]
        assert links[0]["link_type"] == "related"


class TestKnowledgeManager:
    """Tests for Knowledge Manager."""

    def test_knowledge_lifecycle(self, temp_dir, mid_brain):
        """Test knowledge creation and promotion."""
        km = mid_brain.knowledge

        # Create knowledge
        result = km.create_knowledge(
            content="The sky is blue",
            kind=KnowledgeType.FACT,
            importance=0.8,
            confidence=0.9,
            source="test",
        )
        assert result["created"] is True
        kid = result["knowledge_id"]

        # Get and verify
        item = km.get(kid)
        assert item is not None
        assert item.content == "The sky is blue"
        assert item.status == KnowledgeStatus.CANDIDATE
        assert item.version == 1

        # Validate
        result = km.validate_knowledge(kid, validated_by="test", confidence=0.95)
        assert result["success"] is True
        assert result["status"] == KnowledgeStatus.VALIDATED

        # Promote to trusted
        result = km.promote_knowledge(kid, KnowledgeStatus.TRUSTED, promoted_by="test")
        assert result["success"] is True
        assert result["status"] == KnowledgeStatus.TRUSTED

        # Check version history
        history = km.get_knowledge_history(kid)
        assert len(history) == 3  # initial, validated, trusted
        assert history[0]["version"] == 1
        assert history[1]["version"] == 2
        assert history[2]["version"] == 3

    def test_knowledge_deprecation(self, temp_dir, mid_brain):
        """Test knowledge deprecation."""
        km = mid_brain.knowledge

        result = km.create_knowledge(content="Old fact", kind=KnowledgeType.FACT)
        kid = result["knowledge_id"]

        result = km.deprecate_knowledge(kid, deprecated_by="test", reason="Outdated")
        assert result["success"] is True
        assert result["status"] == KnowledgeStatus.DEPRECATED


class TestReasoningEngine:
    """Tests for Reasoning Engine."""

    def test_compare_answers(self, mid_brain):
        """Test answer comparison."""
        re = mid_brain.reasoning

        result = re.compare_answers(
            "The answer is yes",
            "The answer is no",
            "Is it true?"
        )
        assert result["similarity"] < 1.0
        assert len(result["key_differences"]) > 0

    def test_compare_same_answers(self, mid_brain):
        """Test comparison of similar answers."""
        re = mid_brain.reasoning

        result = re.compare_answers(
            "The sky is blue",
            "The sky appears blue",
            "What color is the sky?"
        )
        assert result["similarity"] > 0.3

    def test_calculate_confidence(self, mid_brain):
        """Test confidence calculation."""
        re = mid_brain.reasoning

        evidence = {
            "first_brain_support": 1.0,
            "second_brain_support": 1.0,
            "mid_brain_support": 0.5,
            "evidence_quality": "high",
        }
        conflicts = []

        confidence = re.calculate_confidence(evidence, conflicts, "answer1", "answer2")
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.5  # High evidence should give decent confidence

    def test_confidence_with_conflicts(self, mid_brain):
        """Test confidence decreases with conflicts."""
        re = mid_brain.reasoning

        evidence = {
            "first_brain_support": 1.0,
            "second_brain_support": 1.0,
            "mid_brain_support": 0.5,
            "evidence_quality": "high",
        }
        conflicts = [{"claim_a": "A", "claim_b": "B"}]

        confidence = re.calculate_confidence(evidence, conflicts, "answer1", "answer2")
        assert confidence < 0.9  # Should be reduced due to conflict


class TestConflictEngine:
    """Tests for Conflict Engine."""

    def test_detect_negation_conflict(self, mid_brain):
        """Test detection of negation conflicts."""
        ce = mid_brain.conflict

        conflicts = ce.detect(
            "Yes, it is true",
            "No, it is false",
            "Is it true?"
        )
        assert len(conflicts) > 0
        assert conflicts[0]["severity"] == ConflictSeverity.HIGH

    def test_detect_numerical_conflict(self, mid_brain):
        """Test detection of numerical conflicts."""
        ce = mid_brain.conflict

        conflicts = ce.detect(
            "The value is 100",
            "The value is 200",
            "What is the value?"
        )
        assert len(conflicts) > 0
        assert conflicts[0]["metadata"]["numerical_discrepancy"]["first"] == 100.0

    def test_no_conflict_when_one_empty(self, mid_brain):
        """Test no conflict when one answer is missing."""
        ce = mid_brain.conflict

        conflicts = ce.detect("Answer", None, "Question")
        assert len(conflicts) == 0

        conflicts = ce.detect(None, "Answer", "Question")
        assert len(conflicts) == 0


class TestReferenceEngine:
    """Tests for Reference Engine."""

    def test_index_and_retrieve(self, temp_dir, mid_brain):
        """Test indexing and retrieving references."""
        ref = mid_brain.reference

        ref.index(
            question="What is Python?",
            answer="Python is a programming language",
            confidence=0.9,
            trace_id="trace-1",
            project_id="proj-1",
            tags=["python", "programming"],
        )

        results = ref.retrieve("Python", project_id="proj-1", limit=5)
        assert results["total"] >= 1
        assert "Python" in results["items"][0]["question"]

    def test_find_similar(self, temp_dir, mid_brain):
        """Test finding similar experiences."""
        ref = mid_brain.reference

        ref.index(
            question="How to fix memory leak?",
            answer="Check for circular references",
            confidence=0.8,
            trace_id="trace-2",
            project_id="proj-1",
        )

        similar = ref.find_similar_experience("memory leak", project_id="proj-1")
        assert len(similar) >= 1


class TestReflectionEngine:
    """Tests for Reflection Engine."""

    def test_reflect(self, temp_dir, mid_brain):
        """Test reflection after task."""
        refl = mid_brain.reflection

        steps = [
            {"phase": "RECALL", "output": {"results_count": 5}},
            {"phase": "CONFLICT_DETECTION", "output": {"conflicts_count": 0}},
        ]

        result = refl.reflect(
            question="Test question",
            answer="Test answer",
            confidence=0.85,
            steps=steps,
            project_id="proj-1",
            trace_id="trace-3",
        )
        assert result["stored"] is True
        assert "what_we_knew" in result
        assert "what_to_improve" in result

    def test_get_reflection(self, temp_dir, mid_brain):
        """Test retrieving reflection."""
        refl = mid_brain.reflection

        steps = [{"phase": "TEST"}]
        result = refl.reflect(
            question="Test",
            answer="Answer",
            confidence=0.8,
            steps=steps,
            trace_id="trace-4",
        )

        retrieved = refl.get_reflection(result["reflection_id"])
        assert retrieved is not None
        assert retrieved["question"] == "Test"
        assert retrieved["confidence"] == 0.8


class TestLearningEngine:
    """Tests for Learning Engine."""

    def test_extract_learning(self, temp_dir, mid_brain):
        """Test learning extraction."""
        le = mid_brain.learning

        result = le.extract_learning(
            question="What is the decision?",
            answer="We decided to use Python for the project",
            confidence=0.9,
            project_id="proj-1",
            trace_id="trace-5",
        )
        assert result["stored_count"] > 0
        assert len(result["items"]) > 0

        # Check for decision type
        types = [item["learning_type"] for item in result["items"]]
        assert LearningType.EXPERIENCE in types
        assert LearningType.DECISION in types

    def test_search_learning(self, temp_dir, mid_brain):
        """Test searching learning items."""
        le = mid_brain.learning

        le.extract_learning(
            question="Test",
            answer="We decided to use Python",
            confidence=0.9,
            project_id="proj-1",
        )

        decisions = le.get_decisions(project_id="proj-1")
        assert len(decisions) >= 1

        le.get_lessons(project_id="proj-1")
        # May or may not have lessons depending on content


class TestFullCognitiveLoop:
    """Integration test for the full cognitive loop."""

    def test_process_question(self, mid_brain):
        """Test the full process_question loop."""
        result = mid_brain.process_question(
            question="What is the capital of France?",
            project_id="proj-1",
        )
        assert "answer" in result
        assert "confidence" in result
        assert "trace_id" in result
        assert "steps" in result
        assert len(result["steps"]) > 0

        # Check all phases present
        phases = [s["phase"] for s in result["steps"]]
        expected_phases = ["RECALL", "UNDERSTAND", "QUESTION", "COMPARE",
                          "CONFLICT_DETECTION", "EVIDENCE", "CONFIDENCE",
                          "SYNTHESIS", "DECISION", "REFLECTION", "LEARNING",
                          "MEMORY", "FUTURE_REFERENCE"]
        for phase in expected_phases:
            assert phase in phases

    def test_store_knowledge(self, mid_brain):
        """Test explicit knowledge storage."""
        result = mid_brain.store_knowledge(
            content="Important decision: Use Python 3.11+",
            kind="decision",
            importance=0.9,
            confidence=0.95,
            source="user",
            project_id="proj-1",
        )
        assert result["created"] is True
        assert "knowledge_id" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
