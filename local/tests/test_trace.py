"""Turn trace tests (tini-agent pattern: always-on JSONL, never breaks the loop)."""

from __future__ import annotations

import json
from pathlib import Path

from local.agent import FirstBrainAgent, TaskInput
from local.config import BrainSettings
from local.llm import EchoLLM
from local.memory_client import WriteOutcome
from local.trace import TurnTracer


class StubClient:
    def search(self, query, **kwargs):
        return {"results": []}

    def write_memory(self, **kwargs):
        return WriteOutcome(status="stored", memory_id="stub-1")


def _read_events(trace_dir: Path) -> list[dict]:
    files = sorted(trace_dir.glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_turn_emits_ordered_events(tmp_path):  # type: ignore[no-untyped-def]
    settings = BrainSettings(local_data_dir=str(tmp_path))
    agent = FirstBrainAgent(
        StubClient(), llm=EchoLLM(), settings=settings, trace_dir=str(tmp_path / "traces")
    )
    result = agent.run(TaskInput(question="when am I meeting Alex?", store_result=False))
    assert result.answer

    events = _read_events(tmp_path / "traces")
    names = [e["event"] for e in events]
    assert names == ["turn_start", "gate", "store", "turn_end"]
    assert all(e["turn_id"] == events[0]["turn_id"] for e in events)
    gate = events[1]
    assert gate["retrieve"] is True
    assert events[-1]["verified"] is True


def test_trace_failure_never_breaks_loop(tmp_path):  # type: ignore[no-untyped-def]
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    tracer = TurnTracer(blocker)
    assert tracer.enabled is False
    tracer.event("turn_start")  # must not raise

    settings = BrainSettings(local_data_dir=str(tmp_path))
    agent = FirstBrainAgent(
        StubClient(), llm=EchoLLM(), settings=settings, trace_dir=str(blocker)
    )
    result = agent.run(TaskInput(question="what's 2+2?", store_result=False))
    assert result.answer  # loop unaffected


def test_trace_disabled_by_settings(tmp_path):  # type: ignore[no-untyped-def]
    settings = BrainSettings(local_data_dir=str(tmp_path), trace_enabled=False)
    agent = FirstBrainAgent(StubClient(), llm=EchoLLM(), settings=settings)
    agent.run(TaskInput(question="hello?", store_result=False))
    assert not (tmp_path / "traces").exists()
