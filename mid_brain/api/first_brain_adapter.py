"""First Brain Adapter - Communicates with First Brain (Experience)."""

from __future__ import annotations

import time
from typing import Any

from mid_brain.api.brain_protocol import (
    BrainResponse,
    create_answer,
    create_question,
)


class FirstBrainAdapter:
    """
    Adapter for communicating with First Brain (Experience).

    First Brain handles:
    - Personal experience and episodic memory
    - Real-time reasoning and planning
    - Local LLM interactions
    - Immediate context processing

    Communication: HTTP/gRPC to local First Brain API
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8100",
        api_key: str = "dev-local-key",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._initialized = False
        self._http_client = None

    def initialize(self) -> None:
        """Initialize the adapter."""
        try:
            import httpx
            self._http_client = httpx.Client(
                base_url=self.base_url,
                headers={"X-API-Key": self.api_key} if self.api_key else {},
                timeout=self.timeout_seconds,
            )
            # Test connection
            self._http_client.get("/health", timeout=2.0)
            self._initialized = True
        except Exception:
            self._initialized = False
            # Will use fallback

    def is_available(self) -> bool:
        """Check if First Brain is available."""
        if not self._initialized:
            return False
        try:
            resp = self._http_client.get("/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def ask(
        self,
        question: str,
        project_id: str | None = None,
        trace_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> BrainResponse:
        """
        Send a question to First Brain and get answer.

        Returns BrainResponse with answer or error.
        """
        start_time = time.time()

        if not self.is_available():
            return BrainResponse(
                message=create_answer(
                    source="first-brain",
                    destination="mid-brain",
                    question=question,
                    answer="",
                    confidence=0.0,
                    trace_id=trace_id or "",
                ),
                success=False,
                error="First Brain unavailable",
                duration_ms=(time.time() - start_time) * 1000,
            )

        # Create question message
        msg = create_question(
            source="mid-brain",
            destination="first-brain",
            question=question,
            trace_id=trace_id,
            project_id=project_id,
            context=context,
        )

        try:
            # Send to First Brain API
            # In full impl, would use dedicated endpoint
            # For now, use memory search + agent loop
            resp = self._http_client.post(
                "/v1/memory/search",
                json={
                    "query": question,
                    "project_id": project_id,
                    "top_k": 8,
                },
                timeout=self.timeout_seconds,
            )

            if resp.status_code != 200:
                return BrainResponse(
                    message=create_answer(
                        source="first-brain",
                        destination="mid-brain",
                        question=question,
                        answer="",
                        confidence=0.0,
                        trace_id=msg.trace_id,
                    ),
                    success=False,
                    error=f"First Brain search failed: {resp.status_code}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            search_results = resp.json()
            memories = search_results.get("results", [])

            # Format evidence
            evidence = []
            for i, mem in enumerate(memories[:3]):
                evidence.append(f"[{i+1}] ({mem.get('type')}, score={mem.get('score'):.3f}) {mem.get('title')}: {mem.get('content')[:200]}")

            # In full implementation, would call First Brain agent
            # For now, return formatted evidence as answer
            if memories:
                top = memories[0]
                answer = f"Based on {len(memories)} retrieved memories:\n" + "\n".join(evidence)
                confidence = top.get("score", 0.5)
            else:
                answer = "No relevant memories were available locally or in the Second Brain."
                confidence = 0.1

            return BrainResponse(
                message=create_answer(
                    source="first-brain",
                    destination="mid-brain",
                    question=question,
                    answer=answer,
                    confidence=confidence,
                    trace_id=msg.trace_id,
                    evidence=evidence,
                ),
                success=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as exc:
            return BrainResponse(
                message=create_answer(
                    source="first-brain",
                    destination="mid-brain",
                    question=question,
                    answer="",
                    confidence=0.0,
                    trace_id=msg.trace_id,
                ),
                success=False,
                error=f"First Brain error: {exc}",
                duration_ms=(time.time() - start_time) * 1000,
            )

    def store_experience(
        self,
        content: str,
        question: str,
        trace_id: str,
        project_id: str | None = None,
        confidence: float = 0.8,
    ) -> bool:
        """Store an experience in First Brain's local storage."""
        # In full impl, would call First Brain's local store
        return True

    def shutdown(self) -> None:
        """Shutdown the adapter."""
        if self._http_client:
            self._http_client.close()
        self._initialized = False
