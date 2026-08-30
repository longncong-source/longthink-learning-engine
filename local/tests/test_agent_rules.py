"""Agent loop rules and full-loop behaviour with a stubbed Second Brain."""

from __future__ import annotations

import pytest

from local.agent import (
    FirstBrainAgent,
    TaskInput,
    classify_memory,
    format_evidence,
    is_long_term_worthy,
)
from local.llm import EchoLLM
from local.memory_client import WriteOutcome


class StubClient:
    def __init__(self, results=None, fail_retrieval=False):  # type: ignore[no-untyped-def]
        self.results = results or []
        self.fail_retrieval = fail_retrieval
        self.writes: list[dict] = []

    def search(self, query, **kwargs):
        if self.fail_retrieval:
            raise RuntimeError("cloud down")
        return {"results": self.results}

    def write_memory(self, **kwargs):
        self.writes.append(kwargs)
        return WriteOutcome(status="stored", memory_id="stub-1")


RESULT_FIXTURE = {
    "id": "m1",
    "type": "episodic",
    "title": "Vendor A delay",
    "content": "Vendor A delayed mechanical drawing approval by 21 days.",
    "score": 0.91,
    "metadata": {},
}


class TestClassifyMemory:
    @pytest.mark.parametrize(
        "text,expected_type,min_importance",
        [
            ("We decided to require vendor drawings 14 days before procurement.", "decision", 0.7),
            ("Lesson learned: review drawings before procurement.", "lesson", 0.6),
            ("Vendor missed the submission deadline by 21 days.", "episodic", 0.6),
            ("Project X uses the FIDIC contract model.", "semantic", 0.4),
        ],
    )
    def test_types_and_importance_floor(self, text, expected_type, min_importance):  # type: ignore[no-untyped-def]
        mtype, importance = classify_memory(text)
        assert mtype == expected_type
        assert importance >= min_importance

    def test_decision_outranks_lesson(self):  # type: ignore[no-untyped-def]
        mtype, importance = classify_memory("Decision: approved supplier B after lesson learned")
        assert mtype == "decision"
        assert importance == 0.75


class TestWorthyFilter:
    def test_temporary_never_stored(self):  # type: ignore[no-untyped-def]
        assert is_long_term_worthy("temp note: opened file test.py") is False

    def test_decision_stored(self):  # type: ignore[no-untyped-def]
        assert is_long_term_worthy("We decided to switch suppliers", 0.3) is True

    def test_high_importance_stored(self):  # type: ignore[no-untyped-def]
        assert is_long_term_worthy("Contract requires approval within 7 days", 0.8) is True

    def test_trivial_fact_not_stored(self):  # type: ignore[no-untyped-def]
        assert is_long_term_worthy("opened file main.py today", 0.5) is False


class TestEvidenceFraming:
    def test_evidence_is_data_not_instructions(self):  # type: ignore[no-untyped-def]
        text = format_evidence([RESULT_FIXTURE])
        assert text.startswith("[1]")
        assert "score=0.91" in text

    def test_empty_evidence_marker(self):  # type: ignore[no-untyped-def]
        assert "no relevant memories" in format_evidence([])


class TestAgentLoopPhases:
    def test_all_eight_phases_present(self):  # type: ignore[no-untyped-def]
        agent = FirstBrainAgent(StubClient(results=[RESULT_FIXTURE]), llm=EchoLLM())
        result = agent.run(TaskInput(question="What happened with mechanical drawing delays?",
                                     store_result=False))
        phases = [s.phase for s in result.steps]
        assert phases == ["OBSERVE", "RETRIEVE", "THINK", "PLAN", "EXECUTE", "VERIFY", "REFLECT", "STORE"]
        assert result.memories_used == 1
        assert result.verified is True
        assert result.stored is None  # store_result=False => nothing stored

    def test_cloud_down_does_not_break_loop(self):  # type: ignore[no-untyped-def]
        agent = FirstBrainAgent(StubClient(fail_retrieval=True), llm=EchoLLM())
        result = agent.run(TaskInput(question="anything?", store_result=False))
        retrieve_step = result.steps[1]
        assert "unavailable" in retrieve_step.output
        assert result.answer  # still produces a graceful answer

    def test_reflection_stores_decision(self):  # type: ignore[no-untyped-def]
        stub = StubClient()
        agent = FirstBrainAgent(stub, llm=EchoLLM())
        question = "We decided to require vendor drawings 14 days before procurement."
        result = agent.run(TaskInput(question=question))
        assert result.stored is not None
        assert result.stored.status == "stored"
        write_kwargs = stub.writes[0]
        assert write_kwargs["type"] == "decision"
        assert write_kwargs["importance"] >= 0.75

    def test_store_knowledge_explicit_overrides(self):  # type: ignore[no-untyped-def]
        stub = StubClient()
        agent = FirstBrainAgent(stub, llm=EchoLLM())
        mtype, importance, outcome = agent.store_knowledge(
            "Use supplier B for mechanical package", kind="decision", importance=0.9
        )
        assert mtype == "decision"
        assert importance == 0.9
        assert outcome.status == "stored"
        assert stub.writes[0]["importance"] == 0.9
