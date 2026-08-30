"""Second Brain Adapter - Communicates with Second Brain (Knowledge)."""

from __future__ import annotations

import time
from typing import Any

from mid_brain.api.brain_protocol import (
    BrainResponse,
    create_answer,
    create_conflict,
    create_learn_message,
)


class SecondBrainAdapter:
    """
    Adapter for communicating with Second Brain (Knowledge).

    Second Brain handles:
    - Long-term knowledge storage
    - Hybrid search (semantic + keyword + importance + recency)
    - Document RAG ingestion
    - Project management
    - Memory deduplication

    Communication: HTTP to Second Brain Memory API
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
            resp = self._http_client.get("/health", timeout=2.0)
            if resp.status_code == 200:
                self._initialized = True
            else:
                self._initialized = False
        except Exception:
            self._initialized = False

    def is_available(self) -> bool:
        """Check if Second Brain is available."""
        if not self._initialized:
            return False
        try:
            resp = self._http_client.get("/health", timeout=2.0)
            return resp.status_code == 200
        except Exception:
            return False

    def search(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 8,
        memory_type: str | None = None,
        min_importance: float = 0.0,
    ) -> BrainResponse:
        """Search memories in Second Brain."""
        start_time = time.time()

        if not self.is_available():
            return BrainResponse(
                message=create_answer(
                    source="second-brain",
                    destination="mid-brain",
                    question=query,
                    answer="",
                    confidence=0.0,
                    trace_id="",
                ),
                success=False,
                error="Second Brain unavailable",
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            payload: dict[str, Any] = {"query": query, "top_k": top_k}
            if project_id:
                payload["project_id"] = project_id
            if memory_type:
                payload["filters"] = {"type": memory_type}
            if min_importance > 0:
                payload.setdefault("filters", {})["min_importance"] = min_importance

            resp = self._http_client.post("/v1/memory/search", json=payload, timeout=self.timeout_seconds)

            if resp.status_code != 200:
                return BrainResponse(
                    message=create_answer(
                        source="second-brain",
                        destination="mid-brain",
                        question=query,
                        answer="",
                        confidence=0.0,
                        trace_id="",
                    ),
                    success=False,
                    error=f"Search failed: {resp.status_code}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

            data = resp.json()
            memories = data.get("results", [])

            # Format answer
            if memories:
                evidence = []
                for i, mem in enumerate(memories[:3]):
                    evidence.append(f"[{i+1}] ({mem.get('type')}, score={mem.get('score'):.3f}) {mem.get('title')}: {mem.get('content')[:200]}")

                top = memories[0]
                answer = f"Based on {len(memories)} retrieved memories:\n" + "\n".join(evidence)
                confidence = top.get("score", 0.5)
            else:
                answer = "No relevant memories found in Second Brain."
                confidence = 0.1

            return BrainResponse(
                message=create_answer(
                    source="second-brain",
                    destination="mid-brain",
                    question=query,
                    answer=answer,
                    confidence=confidence,
                    trace_id="",
                    evidence=evidence if memories else [],
                ),
                success=True,
                duration_ms=(time.time() - start_time) * 1000,
            )

        except Exception as exc:
            return BrainResponse(
                message=create_answer(
                    source="second-brain",
                    destination="mid-brain",
                    question=query,
                    answer="",
                    confidence=0.0,
                    trace_id="",
                ),
                success=False,
                error=f"Second Brain error: {exc}",
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
        """Store a memory in Second Brain."""
        start_time = time.time()

        if not self.is_available():
            return BrainResponse(
                message=create_answer(
                    source="second-brain",
                    destination="mid-brain",
                    question=title,
                    answer="",
                    confidence=0.0,
                    trace_id="",
                ),
                success=False,
                error="Second Brain unavailable",
                duration_ms=(time.time() - start_time) * 1000,
            )

        try:
            payload: dict[str, Any] = {
                "type": memory_type,
                "title": title,
                "content": content,
                "importance": importance,
                "confidence": confidence,
                "source": source,
            }
            if project_id:
                payload["project_id"] = project_id
            if metadata:
                payload["metadata"] = metadata

            resp = self._http_client.post("/v1/memory", json=payload, timeout=self.timeout_seconds)

            if resp.status_code == 201:
                data = resp.json()
                memory = data.get("memory", {})
                return BrainResponse(
                    message=create_answer(
                        source="second-brain",
                        destination="mid-brain",
                        question=f"Store: {title}",
                        answer=f"Memory stored with ID: {memory.get('id')}",
                        confidence=1.0,
                        trace_id="",
                    ),
                    success=True,
                    duration_ms=(time.time() - start_time) * 1000,
                )
            else:
                return BrainResponse(
                    message=create_answer(
                        source="second-brain",
                        destination="mid-brain",
                        question=f"Store: {title}",
                        answer="",
                        confidence=0.0,
                        trace_id="",
                    ),
                    success=False,
                    error=f"Store failed: {resp.status_code} - {resp.text}",
                    duration_ms=(time.time() - start_time) * 1000,
                )

        except Exception as exc:
            return BrainResponse(
                message=create_answer(
                    source="second-brain",
                    destination="mid-brain",
                    question=f"Store: {title}",
                    answer="",
                    confidence=0.0,
                    trace_id="",
                ),
                success=False,
                error=f"Second Brain store error: {exc}",
                duration_ms=(time.time() - start_time) * 1000,
            )

    def verify_claim(
        self,
        claim: str,
        evidence: list[str],
        trace_id: str,
    ) -> BrainResponse:
        """Verify a claim against Second Brain knowledge."""
        # Search for supporting/contradicting evidence
        return self.search(claim, top_k=10)

    def report_conflict(
        self,
        claim_a: str,
        claim_b: str,
        source_a: str,
        source_b: str,
        trace_id: str,
        severity: str = "medium",
    ) -> BrainResponse:
        """Report a conflict to Second Brain for tracking."""
        msg = create_conflict(
            source="mid-brain",
            destination="second-brain",
            claim_a=claim_a,
            claim_b=claim_b,
            source_a=source_a,
            source_b=source_b,
            trace_id=trace_id,
            severity=severity,
        )

        # In full impl, would POST to /v1/conflicts
        # For now, just acknowledge
        return BrainResponse(
            message=msg,
            success=True,
            duration_ms=0,
        )

    def learn(
        self,
        learning_type: str,
        content: str,
        confidence: float,
        trace_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> BrainResponse:
        """Send learning to Second Brain for long-term storage."""
        msg = create_learn_message(
            source="mid-brain",
            destination="second-brain",
            learning_type=learning_type,
            content=content,
            confidence=confidence,
            trace_id=trace_id,
            metadata=metadata,
        )

        # In full impl, would POST to /v1/learning
        return BrainResponse(
            message=msg,
            success=True,
            duration_ms=0,
        )

    def get_projects(self) -> list[dict]:
        """Get all projects from Second Brain."""
        if not self.is_available():
            return []
        try:
            resp = self._http_client.get("/v1/projects", timeout=self.timeout_seconds)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return []

    def ensure_project(self, name: str, description: str = "") -> str | None:
        """Ensure a project exists, create if needed."""
        projects = self.get_projects()
        for p in projects:
            if p.get("name", "").lower() == name.lower():
                return str(p["id"])

        if not self.is_available():
            return None

        try:
            resp = self._http_client.post(
                "/v1/projects",
                json={"name": name, "description": description},
                timeout=self.timeout_seconds,
            )
            if resp.status_code == 201:
                return str(resp.json().get("id"))
        except Exception:
            pass
        return None

    def shutdown(self) -> None:
        """Shutdown the adapter."""
        if self._http_client:
            self._http_client.close()
        self._initialized = False
