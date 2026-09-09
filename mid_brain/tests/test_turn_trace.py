"""Mid Brain turn trace tests (tini-agent pattern: always-on JSONL)."""

from __future__ import annotations

import json
from pathlib import Path

from mid_brain.core.mid_brain import MidBrain, MidBrainConfig
from mid_brain.ops.turn_trace import TurnTracer


def _read_events(trace_dir: Path) -> list[dict]:
    files = sorted(trace_dir.glob("*.jsonl"))
    assert len(files) == 1
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]


def test_tracer_appends_and_disables_on_failure(tmp_path):  # type: ignore[no-untyped-def]
    tracer = TurnTracer(tmp_path / "traces")
    assert tracer.enabled is True
    tracer.event("turn_start", question="hi")
    tracer.event("turn_end", ok=True)
    events = _read_events(tmp_path / "traces")
    assert [e["event"] for e in events] == ["turn_start", "turn_end"]
    assert events[0]["turn_id"] == events[1]["turn_id"]

    assert TurnTracer(None).enabled is False
    TurnTracer(None).event("turn_start")  # must not raise

    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    assert TurnTracer(blocker).enabled is False


def _quiet_brain(tmp_path):  # type: ignore[no-untyped-def]
    config = MidBrainConfig(
        first_brain_url="http://127.0.0.1:9",
        second_brain_url="http://127.0.0.1:9",
        trace_dir=str(tmp_path / "traces"),
        enable_reflection=False,
        enable_learning=False,
        enable_conflict_detection=False,
        enable_reference=False,
        enable_planning=False,
        enable_agent=False,
        enable_confidence=False,
        enable_network=False,
        enable_obsidian=False,
    )
    brain = MidBrain(config)
    brain.initialize()
    return brain


def test_orchestrator_gate_and_trace(tmp_path):  # type: ignore[no-untyped-def]
    brain = _quiet_brain(tmp_path)
    try:
        result = brain.process_question("what's 2+2?")
        assert result["gate"] == "skip"
        assert result["memories_used"] == 0
        recall = next(s for s in result["steps"] if s["phase"] == "RECALL")
        assert recall["output"]["gate"] == "skip"

        events = _read_events(tmp_path / "traces")
        names = [e["event"] for e in events]
        assert names == ["turn_start", "turn_end"]
        assert events[-1]["gate"] == "skip"
    finally:
        brain.shutdown()
