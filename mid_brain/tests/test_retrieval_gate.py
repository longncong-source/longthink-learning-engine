"""Mid Brain retrieval gate rules (tini-agent pattern)."""

from __future__ import annotations

import pytest

from mid_brain.memory.retrieval_gate import should_retrieve


@pytest.mark.parametrize("message", ["what's 2+2?", "12 × 8", "thanks!", "hello"])
def test_skip_without_memory(message):  # type: ignore[no-untyped-def]
    decision = should_retrieve(message)
    assert decision.retrieve is False
    assert decision.reason


@pytest.mark.parametrize(
    "message",
    [
        "when am I meeting Alex?",
        "Remember that Raj prefers evening games",
        "anything?",
    ],
)
def test_retrieve_fail_open(message):  # type: ignore[no-untyped-def]
    decision = should_retrieve(message)
    assert decision.retrieve is True
    assert decision.query == message.strip()


def test_empty_skips():  # type: ignore[no-untyped-def]
    assert should_retrieve("   ").retrieve is False
