"""Consolidation tests (tini-agent pattern: raw turns -> durable facts)."""

from __future__ import annotations

from local.agent import FirstBrainAgent, TaskInput
from local.config import BrainSettings
from local.consolidation import consolidate_if_due, extract_candidates
from local.llm import EchoLLM
from local.local_store import LocalStore
from local.memory_client import WriteOutcome


class StubClient:
    def search(self, query, **kwargs):
        return {"results": []}

    def write_memory(self, **kwargs):
        return WriteOutcome(status="stored", memory_id="stub-1")


class BoomLLM(EchoLLM):
    def complete(self, system, prompt):  # type: ignore[no-untyped-def]
        raise RuntimeError("llm down")


class SilentLLM(EchoLLM):
    """Refine-pass returns nothing, so facts stay exactly deterministic."""

    def complete(self, system, prompt):  # type: ignore[no-untyped-def]
        return ""


def _agent(tmp_path, **kwargs):  # type: ignore[no-untyped-def]
    settings = BrainSettings(local_data_dir=str(tmp_path))
    store = LocalStore(tmp_path / "long_term.sqlite3")
    return FirstBrainAgent(
        StubClient(),
        llm=kwargs.pop("llm", SilentLLM()),
        settings=settings,
        store=store,
        trace_dir=str(tmp_path / "traces"),
        consolidate_every=kwargs.pop("consolidate_every", 6),
        **kwargs,
    ), store


def test_consolidates_after_n_turns(tmp_path):  # type: ignore[no-untyped-def]
    agent, store = _agent(tmp_path)
    last = None
    for i in range(6):
        last = agent.run(
            TaskInput(question=f"We decided to use supplier {chr(65 + i)} for package {i}.")
        )
    assert last is not None
    assert last.consolidated_facts == 6
    assert store.unconsolidated_count() == 0
    facts = [n for n in store.list_notes(limit=50) if n["kind"] == "consolidated_fact"]
    assert len(facts) == 6


def test_no_consolidation_before_threshold(tmp_path):  # type: ignore[no-untyped-def]
    agent, store = _agent(tmp_path)
    for _ in range(2):
        result = agent.run(TaskInput(question="We decided to switch suppliers."))
    assert result.consolidated_facts == 0
    assert store.unconsolidated_count() == 2


def test_summarizer_fail_loses_nothing(tmp_path):  # type: ignore[no-untyped-def]
    agent, store = _agent(tmp_path, llm=BoomLLM())
    last = None
    for i in range(6):
        last = agent.run(TaskInput(question=f"We decided to freeze scope for milestone {i}."))
    assert last is not None
    assert last.consolidated_facts > 0  # deterministic extraction still works
    assert store.unconsolidated_count() == 0  # only read IDs marked, none lost


def test_consolidation_is_idempotent(tmp_path):  # type: ignore[no-untyped-def]
    agent, store = _agent(tmp_path)
    for _ in range(6):
        agent.run(TaskInput(question="We decided to switch suppliers."))
    report = consolidate_if_due(store, every_n=1)
    assert report["ran"] is False  # nothing left unconsolidated


def test_trivial_turns_yield_no_facts(tmp_path):  # type: ignore[no-untyped-def]
    assert extract_candidates("what's 2+2?", "4") == []
    store = LocalStore(tmp_path / "long_term.sqlite3")
    for _ in range(6):
        store.log_turn("what's 2+2?", "4", "type=semantic")
    report = consolidate_if_due(store, every_n=6)
    assert report == {"ran": True, "turns": 6, "facts": 0}
