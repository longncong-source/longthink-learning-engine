"""Retrieval gate rules + loop integration (tini-agent pattern)."""

from __future__ import annotations

import pytest

from local.agent import FirstBrainAgent, TaskInput
from local.llm import EchoLLM
from local.retrieval_gate import should_retrieve


class StubClient:
    def __init__(self):  # type: ignore[no-untyped-def]
        self.searches = 0

    def search(self, query, **kwargs):
        self.searches += 1
        return {"results": []}

    def write_memory(self, **kwargs):
        raise AssertionError("must not store for gate tests")


class TestGate:
    @pytest.mark.parametrize(
        "message",
        ["what's 2+2?", "12 × 8", "thanks!", "hello"],
    )
    def test_skip_without_memory(self, message):  # type: ignore[no-untyped-def]
        decision = should_retrieve(message)
        assert decision.retrieve is False
        assert decision.reason

    @pytest.mark.parametrize(
        "message",
        [
            "when am I meeting Alex?",
            "Remember that Raj prefers evening games",
            "anything?",
            "What happened with mechanical drawing delays?",
        ],
    )
    def test_retrieve_fail_open(self, message):  # type: ignore[no-untyped-def]
        decision = should_retrieve(message)
        assert decision.retrieve is True
        assert decision.query == message.strip()

    def test_empty_skips(self):  # type: ignore[no-untyped-def]
        assert should_retrieve("   ").retrieve is False


class TestGateInLoop:
    def test_math_skips_store_search(self):  # type: ignore[no-untyped-def]
        stub = StubClient()
        agent = FirstBrainAgent(stub, llm=EchoLLM())
        result = agent.run(TaskInput(question="what's 2+2?", store_result=False))
        assert stub.searches == 0
        assert result.memories_used == 0
        assert result.gate_retrieve is False
        assert "gate · skip" in result.steps[1].output

    def test_memory_question_still_retrieves(self):  # type: ignore[no-untyped-def]
        stub = StubClient()
        agent = FirstBrainAgent(stub, llm=EchoLLM())
        result = agent.run(TaskInput(question="when am I meeting Alex?", store_result=False))
        assert stub.searches == 1
        assert result.gate_retrieve is True
        assert "gate · retrieve" in result.steps[1].output
