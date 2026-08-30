"""Mock Adapters for testing Mid Brain without external dependencies."""

from __future__ import annotations

import time
from typing import Any

from mid_brain.api.brain_protocol import (
    BrainResponse,
    create_answer,
)
from mid_brain.api.first_brain_adapter import FirstBrainAdapter
from mid_brain.api.second_brain_adapter import SecondBrainAdapter


class MockFirstBrainAdapter(FirstBrainAdapter):
    """
    Mock First Brain Adapter for testing.

    Simulates First Brain behavior with configurable responses.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mock_answers: dict[str, str] = {}
        self._mock_evidence: dict[str, list[str]] = {}
        self._mock_confidence: dict[str, float] = {}
        self._call_log: list[dict] = []
        self._initialized = True  # Always available in mock

    def set_mock_answer(self, question_pattern: str, answer: str, confidence: float = 0.8, evidence: list[str] | None = None) -> None:
        """Set a mock answer for a question pattern."""
        self._mock_answers[question_pattern.lower()] = answer
        self._mock_confidence[question_pattern.lower()] = confidence
        if evidence:
            self._mock_evidence[question_pattern.lower()] = evidence

    def is_available(self) -> bool:
        return True

    def ask(
        self,
        question: str,
        project_id: str | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> BrainResponse:
        start_time = time.time()

        # Log the call
        self._call_log.append({
            "method": "ask",
            "question": question,
            "project_id": project_id,
            "trace_id": trace_id,
            "context": context,
        })

        # Find matching mock answer
        answer = ""
        confidence = 0.1
        evidence = []

        for pattern, mock_answer in self._mock_answers.items():
            if pattern in question.lower():
                answer = mock_answer
                confidence = self._mock_confidence.get(pattern, 0.8)
                evidence = self._mock_evidence.get(pattern, [])
                break

        if not answer:
            answer = f"[Mock First Brain] No specific answer for: {question}"
            confidence = 0.1

        return BrainResponse(
            message=create_answer(
                source="first-brain",
                destination="mid-brain",
                question=question,
                answer=answer,
                confidence=confidence,
                trace_id=trace_id or "",
                evidence=evidence,
            ),
            success=True,
            duration_ms=(time.time() - start_time) * 1000,
        )

    def get_call_log(self) -> list[dict]:
        """Get the call log for verification."""
        return self._call_log

    def clear_log(self) -> None:
        """Clear the call log."""
        self._call_log.clear()


class MockSecondBrainAdapter(SecondBrainAdapter):
    """
    Mock Second Brain Adapter for testing.

    Simulates Second Brain behavior with configurable memories.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._mock_memories: list[dict] = []
        self._mock_projects: list[dict] = []
        self._stored_memories: list[dict] = []
        self._call_log: list[dict] = []
        self._initialized = True  # Always available in mock

    def add_mock_memory(
        self,
        content: str,
        title: str = "",
        memory_type: str = "semantic",
        score: float = 0.8,
        project_id: str | None = None,
    ) -> None:
        """Add a mock memory to search results."""
        memory = {
            "id": f"mock-{len(self._mock_memories)}",
            "title": title or content[:50],
            "content": content,
            "type": memory_type,
            "score": score,
            "project_id": project_id,
            "importance": 0.5,
            "confidence": 0.8,
        }
        self._mock_memories.append(memory)

    def add_mock_project(self, name: str, project_id: str | None = None) -> str:
        """Add a mock project."""
        pid = project_id or f"proj-{len(self._mock_projects)}"
        project = {"id": pid, "name": name, "status": "active"}
        self._mock_projects.append(project)
        return pid

    def is_available(self) -> bool:
        return True

    def search(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 8,
        memory_type: str | None = None,
        min_importance: float = 0.0,
    ) -> BrainResponse:
        start_time = time.time()

        self._call_log.append({
            "method": "search",
            "query": query,
            "project_id": project_id,
            "top_k": top_k,
            "memory_type": memory_type,
        })

        # Filter mock memories
        results = []
        for mem in self._mock_memories:
            if project_id and mem.get("project_id") != project_id:
                continue
            if memory_type and mem.get("type") != memory_type:
                continue
            if mem.get("importance", 0) < min_importance:
                continue
            # Simple keyword match
            if query.lower() in mem.get("content", "").lower() or query.lower() in mem.get("title", "").lower():
                results.append(mem)

        # Sort by score
        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        results = results[:top_k]

        if results:
            evidence = []
            for i, mem in enumerate(results[:3]):
                evidence.append(f"[{i+1}] ({mem.get('type')}, score={mem.get('score'):.3f}) {mem.get('title')}: {mem.get('content')[:200]}")

            top = results[0]
            answer = f"Based on {len(results)} retrieved memories:\n" + "\n".join(evidence)
            confidence = top.get("score", 0.5)
        else:
            answer = "No relevant memories found in Second Brain."
            confidence = 0.1
            evidence = []

        return BrainResponse(
            message=create_answer(
                source="second-brain",
                destination="mid-brain",
                question=query,
                answer=answer,
                confidence=confidence,
                trace_id="",
                evidence=evidence,
            ),
            success=True,
            duration_ms=(time.time() - start_time) * 1000,
        )

    def store_memory(
        self,
        content: str,
        title: str,
        memory_type: str = "semantic",
        project_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str = "mid-brain",
        metadata: dict[str, Any] | None = None,
    ) -> BrainResponse:
        start_time = time.time()

        self._call_log.append({
            "method": "store_memory",
            "title": title,
            "content": content,
            "memory_type": memory_type,
            "project_id": project_id,
        })

        memory_id = f"stored-{len(self._stored_memories)}"
        self._stored_memories.append({
            "id": memory_id,
            "title": title,
            "content": content,
            "type": memory_type,
            "project_id": project_id,
            "importance": importance,
            "confidence": confidence,
            "source": source,
            "metadata": metadata,
        })

        return BrainResponse(
            message=create_answer(
                source="second-brain",
                destination="mid-brain",
                question=f"Store: {title}",
                answer=f"Memory stored with ID: {memory_id}",
                confidence=1.0,
                trace_id="",
            ),
            success=True,
            duration_ms=(time.time() - start_time) * 1000,
        )

    def get_projects(self) -> list[dict]:
        self._call_log.append({"method": "get_projects"})
        return self._mock_projects

    def ensure_project(self, name: str, description: str = "") -> str | None:
        self._call_log.append({"method": "ensure_project", "name": name})
        for p in self._mock_projects:
            if p.get("name", "").lower() == name.lower():
                return str(p["id"])

        pid = f"proj-{len(self._mock_projects)}"
        self._mock_projects.append({"id": pid, "name": name, "status": "active", "description": description})
        return pid

    def get_call_log(self) -> list[dict]:
        """Get the call log for verification."""
        return self._call_log

    def clear_log(self) -> None:
        """Clear the call log."""
        self._call_log.clear()

    def get_stored_memories(self) -> list[dict]:
        """Get all stored memories."""
        return self._stored_memories
