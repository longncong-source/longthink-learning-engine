"""LONGTHINK ORGANIZATION CORE — Phase 04 external-core adapter contracts.

Master rule: DO NOT GUESS unknown external APIs. This module defines only
port interfaces (capabilities from 00_MASTER_EXECUTION section 6) plus
deterministic MOCK implementations for local dev/tests. Real adapters
(Knowledge/Intelligence/Internal Agent) land in Phase 08/09.

Capability map:
- Knowledge Core: SEARCH, RETRIEVE, CITE, FEEDBACK, KNOWLEDGE_CANDIDATE
- Intelligence Core: ASK, PLAN, EXECUTE, EVALUATE
- Internal Agent: EXECUTE, GET_STATUS, CANCEL
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class AdapterConfig:
    backend: str = "mock"  # mock | real (real = Phase 08/09)
    endpoint: str | None = None
    api_key_hint: str | None = None  # never store real secrets here


class KnowledgePort(ABC):
    capability = "knowledge"

    @abstractmethod
    def search(self, query: str, context: dict) -> dict:
        """SEARCH: retrieve candidate knowledge for a query."""

    @abstractmethod
    def retrieve(self, ref_id: str) -> dict:
        """RETRIEVE: fetch one knowledge item by reference."""

    @abstractmethod
    def cite(self, ref_id: str) -> dict:
        """CITE: return citation metadata for evidence."""

    @abstractmethod
    def feedback(self, ref_id: str, useful: bool) -> dict:
        """FEEDBACK: report whether a citation was useful."""

    @abstractmethod
    def knowledge_candidate(self, draft: dict) -> dict:
        """KNOWLEDGE_CANDIDATE: propose a draft for the knowledge base."""


class IntelligencePort(ABC):
    capability = "intelligence"

    @abstractmethod
    def ask(self, question: str, context: dict) -> dict:
        """ASK: reason over a question with organization context."""

    @abstractmethod
    def plan(self, goal: str, context: dict) -> dict:
        """PLAN: produce a plan for a goal."""

    @abstractmethod
    def execute(self, plan_id: str, context: dict) -> dict:
        """EXECUTE: run an approved plan (intelligence-side)."""

    @abstractmethod
    def evaluate(self, result: dict, context: dict) -> dict:
        """EVALUATE: score alternatives/outcomes."""


class InternalAgentPort(ABC):
    capability = "internal_agent"

    @abstractmethod
    def execute(self, action: str, payload: dict) -> dict:
        """EXECUTE an authorized action."""

    @abstractmethod
    def get_status(self, task_id: str) -> dict:
        """GET_STATUS of a submitted execution."""

    @abstractmethod
    def cancel(self, task_id: str) -> dict:
        """CANCEL a submitted execution if the backend supports it."""


@dataclass(slots=True)
class MockKnowledgeAdapter(KnowledgePort):
    config: AdapterConfig = field(default_factory=AdapterConfig)

    def search(self, query: str, context: dict) -> dict:
        return {
            "backend": "mock",
            "results": [
                {"ref_id": "mock-doc-1", "title": "Mock knowledge hit",
                 "snippet": f"Mock evidence for: {query[:80]}"},
            ],
        }

    def retrieve(self, ref_id: str) -> dict:
        return {"backend": "mock", "ref_id": ref_id, "content": "Mock content."}

    def cite(self, ref_id: str) -> dict:
        return {"backend": "mock", "ref_id": ref_id,
                "citation": f"[mock-cite:{ref_id}]"}

    def feedback(self, ref_id: str, useful: bool) -> dict:
        return {"backend": "mock", "ref_id": ref_id, "recorded": True,
                "useful": useful}

    def knowledge_candidate(self, draft: dict) -> dict:
        return {"backend": "mock", "accepted": False,
                "reason": "mock backend never persists drafts"}


@dataclass(slots=True)
class MockIntelligenceAdapter(IntelligencePort):
    config: AdapterConfig = field(default_factory=AdapterConfig)

    def ask(self, question: str, context: dict) -> dict:
        person = (context.get("person") or {}).get("code", "?")
        return {"backend": "mock",
                "answer": f"[mock-intelligence] {person}: {question[:120]}",
                "confidence": 0.5}

    def plan(self, goal: str, context: dict) -> dict:
        return {"backend": "mock", "plan_id": "mock-plan-1",
                "steps": [f"Mock step for: {goal[:80]}"]}

    def execute(self, plan_id: str, context: dict) -> dict:
        return {"backend": "mock", "plan_id": plan_id, "status": "refused",
                "reason": "mock intelligence never executes; use Internal Agent"}

    def evaluate(self, result: dict, context: dict) -> dict:
        return {"backend": "mock", "score": 0.5}


@dataclass(slots=True)
class MockInternalAgentAdapter(InternalAgentPort):
    config: AdapterConfig = field(default_factory=AdapterConfig)
    executed: list = field(default_factory=list)

    def execute(self, action: str, payload: dict) -> dict:
        task_id = f"mock-exec-{len(self.executed) + 1}"
        self.executed.append({"task_id": task_id, "action": action,
                              "payload": payload})
        return {"backend": "mock", "task_id": task_id, "status": "completed",
                "action": action}

    def get_status(self, task_id: str) -> dict:
        return {"backend": "mock", "task_id": task_id, "status": "completed"}

    def cancel(self, task_id: str) -> dict:
        return {"backend": "mock", "task_id": task_id, "status": "cancelled"}


@dataclass(slots=True)
class AdapterBundle:
    knowledge: KnowledgePort = field(
        default_factory=MockKnowledgeAdapter)
    intelligence: IntelligencePort = field(
        default_factory=MockIntelligenceAdapter)
    internal_agent: InternalAgentPort = field(
        default_factory=MockInternalAgentAdapter)

    @classmethod
    def mocks(cls) -> AdapterBundle:
        return cls()
