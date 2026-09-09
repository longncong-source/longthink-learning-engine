"""First Brain consolidation (tini-agent pattern): raw turns -> durable facts.

After ``every_n`` unconsolidated turns, distill them into durable local facts
(stored as ``session_notes`` with kind ``consolidated_fact``).

Rules honoured here (mirrors tini's ``consolidate_if_due``):
  - Deterministic extraction first: reuses :func:`local.agent.classify_memory`
    heuristics, so consolidation works fully offline.
  - An LLM pass may *add* candidates, never remove them; its failure is
    swallowed — summarizer fail != lose conversation.
  - ``turn_log`` is append-only and never deleted; only the IDs actually read
    are marked consolidated, so turns arriving mid-run stay pending.
"""

from __future__ import annotations

from typing import Any

from local.local_store import LocalStore
from local.memory_rules import classify_memory, is_long_term_worthy

_KIND = "consolidated_fact"


def extract_candidates(question: str, answer: str) -> list[str]:
    """Deterministic fact candidates from one turn (offline-safe)."""
    text = f"{question.strip()} {answer.strip()}".strip()
    if not text:
        return []
    mtype, importance = classify_memory(text)
    if not is_long_term_worthy(text, importance):
        return []
    if mtype in {"decision", "lesson"}:
        return [question.strip() or answer.strip()]
    return [answer.strip()[:500] or question.strip()]


def _refine_with_llm(llm: Any, turns: list[dict]) -> list[str]:
    """Best-effort LLM pass. Strictly additive; any failure returns []."""
    try:
        lines = "\n".join(f"Q: {t['question']}\nA: {t['answer']}" for t in turns)
        prompt = (
            "Extract durable facts worth remembering (decisions, preferences, "
            "lessons). One fact per line, no numbering, no commentary. "
            "Reply with nothing if there are none.\n\n" + lines
        )
        text = llm.complete("You distill conversation into durable facts.", prompt)
    except Exception:
        return []
    return [ln.strip(" -•\t") for ln in str(text).splitlines() if ln.strip()]


def consolidate_if_due(
    store: LocalStore,
    *,
    every_n: int = 6,
    batch: int = 12,
    llm: Any | None = None,
) -> dict:
    """Distill unconsolidated turns into facts when due. Never raises."""
    try:
        if every_n <= 0 or store.unconsolidated_count() < every_n:
            return {"ran": False, "turns": 0, "facts": 0}
        turns = store.unconsolidated_turns(limit=batch)
        if not turns:
            return {"ran": False, "turns": 0, "facts": 0}

        candidates: list[str] = []
        for turn in turns:
            candidates.extend(extract_candidates(turn["question"], turn["answer"]))
        if llm is not None:
            candidates.extend(_refine_with_llm(llm, turns))

        seen = {
            n["content"].strip().lower()
            for n in store.list_notes(limit=500)
            if n.get("kind") == _KIND
        }
        fresh = []
        for cand in candidates:
            key = cand.strip().lower()
            if cand.strip() and key not in seen:
                seen.add(key)
                fresh.append(cand.strip())

        for fact in fresh:
            store.add_note(_KIND, fact)
        store.mark_turns_consolidated([t["id"] for t in turns])
        return {"ran": True, "turns": len(turns), "facts": len(fresh)}
    except Exception:
        return {"ran": False, "turns": 0, "facts": 0}
