"""Second Brain client for the First Brain.

Implements spec sections:
    11 - retrieval with local TTL cache
    19 - DATA_POLICY enforcement (local_only / selective / cloud_allowed)
    20 - client-side secret redaction before upload
    23 - pending write queue + sync retry when cloud is unavailable
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from local.config import BrainSettings
from local.local_store import LocalStore
from local.redaction import redact_secrets


class SecondBrainUnavailable(RuntimeError):
    pass


class AuthFailure(RuntimeError):
    pass


@dataclass(slots=True)
class WriteOutcome:
    status: str  # stored | queued | skipped_policy | rejected
    memory_id: str | None = None
    deduplicated: bool | None = None
    redaction_count: int = 0
    detail: str = ""


@dataclass(slots=True)
class SyncReport:
    sent: int = 0
    permanent_failures: int = 0
    remaining: int = 0
    errors: list[str] = field(default_factory=list)


class SecondBrainClient:
    def __init__(
        self,
        settings: BrainSettings | None = None,
        store: LocalStore | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings or BrainSettings()
        headers = {}
        if self.settings.second_brain_api_key:
            headers["X-API-Key"] = self.settings.second_brain_api_key
        self._http = httpx.Client(
            base_url=self.settings.second_brain_url.rstrip("/"),
            headers=headers,
            timeout=self.settings.request_timeout_seconds,
            transport=transport,
        )
        self.store = store or LocalStore(Path(self.settings.local_data_dir) / "local.db")

    # ------------------------------------------------------------------ health
    def health(self) -> dict | None:
        """Return health body or None when unreachable (never raises)."""
        try:
            resp = self._http.get("/health")
            if resp.status_code == 200:
                return resp.json()
            return None
        except httpx.HTTPError:
            return None

    def details(self) -> tuple[int | None, dict | None]:
        """Authenticated /health/details - returns (status_code|None, body|None)."""
        try:
            resp = self._http.get("/health/details")
        except httpx.HTTPError:
            return None, None
        body: dict | None = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, body

    # ------------------------------------------------------------------ search
    def search(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int | None = None,
        mtype: str | list[str] | None = None,
        min_importance: float | None = None,
    ) -> dict:
        payload: dict[str, Any] = {"query": query, "top_k": top_k or self.settings.memory_top_k}
        filters: dict[str, Any] = {}
        if project_id:
            payload["project_id"] = project_id
        if mtype is not None:
            filters["type"] = mtype
        if min_importance is not None:
            filters["min_importance"] = min_importance
        if filters:
            payload["filters"] = filters

        cache_key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        cached = self.store.cache_get(cache_key)
        if cached is not None:
            cached = dict(cached)
            cached["_cache"] = "hit"
            return cached

        try:
            resp = self._http.post("/v1/memory/search", json=payload)
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code >= 500:
            raise SecondBrainUnavailable(f"Second Brain error HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise SecondBrainUnavailable(f"Search rejected HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        self.store.cache_set(cache_key, data, ttl_seconds=self.settings.cache_ttl_seconds)
        return data

    # ------------------------------------------------------------------ writes
    def _policy_allows_send(self, allow_cloud: bool | None) -> bool:
        policy = self.settings.data_policy
        if policy == "local_only":
            return False
        if allow_cloud is None:
            # selective & cloud_allowed default to sending for explicit user actions;
            # the agent layer applies its own selectivity before calling.
            return True
        return bool(allow_cloud)

    def write_memory(
        self,
        *,
        title: str,
        content: str,
        type: str = "semantic",
        importance: float = 0.5,
        confidence: float = 0.8,
        source: str | None = None,
        summary: str | None = None,
        metadata: dict | None = None,
        project_id: str | None = None,
        allow_cloud: bool | None = None,
    ) -> WriteOutcome:
        title_r = redact_secrets(title)
        content_r = redact_secrets(content)
        summary_r = redact_secrets(summary or "")
        redaction_count = title_r.count + content_r.count + summary_r.count

        if not self._policy_allows_send(allow_cloud):
            self.store.add_note("local_only_memory", f"{title_r.text}\n{content_r.text}")
            return WriteOutcome(status="skipped_policy", redaction_count=redaction_count)

        payload: dict[str, Any] = {
            "type": type,
            "title": title_r.text,
            "content": content_r.text,
            "importance": importance,
            "confidence": confidence,
            "metadata": dict(metadata or {}),
        }
        if summary_r.text:
            payload["summary"] = summary_r.text
        if source:
            payload["source"] = source
        if project_id:
            payload["project_id"] = project_id

        status_code, body = self._post_memory(payload)
        if status_code is None:
            queued_id = self.store.enqueue_write(payload)
            return WriteOutcome(
                status="queued",
                redaction_count=redaction_count,
                detail=f"queued locally as #{queued_id}",
            )
        if status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if status_code == 201 and isinstance(body, dict):
            memory = body.get("memory", {})
            return WriteOutcome(
                status="stored",
                memory_id=memory.get("id"),
                deduplicated=bool(body.get("deduplicated")),
                redaction_count=redaction_count + int(body.get("redaction_count") or 0),
            )
        return WriteOutcome(
            status="rejected",
            redaction_count=redaction_count,
            detail=f"HTTP {status_code}: {json.dumps(body)[:300] if body else 'no body'}",
        )

    def _post_memory(self, payload: dict) -> tuple[int | None, dict | None]:
        try:
            resp = self._http.post("/v1/memory", json=payload)
        except httpx.HTTPError:
            return None, None
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, body

    # ---------------------------------------------------------------- projects
    def projects(self) -> list[dict]:
        try:
            resp = self._http.get("/v1/projects", params={"limit": 500})
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code >= 400:
            raise SecondBrainUnavailable(f"Projects listing failed HTTP {resp.status_code}")
        data = resp.json()
        return data if isinstance(data, list) else []

    def ensure_project(self, name: str, description: str = "") -> str:
        for project in self.projects():
            if project.get("name", "").lower() == name.lower():
                return str(project["id"])
        try:
            resp = self._http.post(
                "/v1/projects", json={"name": name, "description": description}
            )
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code == 409:
            for project in self.projects():
                if project.get("name", "").lower() == name.lower():
                    return str(project["id"])
            raise SecondBrainUnavailable("Project conflict but name lookup failed")
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code != 201:
            raise SecondBrainUnavailable(f"Project creation failed HTTP {resp.status_code}")
        created = resp.json()
        return str(created["id"])

    # ------------------------------------------------------------------ listing
    def list_memories(
        self,
        limit: int = 20,
        project_id: str | None = None,
        mtype: str | None = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if project_id:
            params["project_id"] = project_id
        if mtype:
            params["type"] = mtype
        try:
            resp = self._http.get("/v1/memory", params=params)
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code >= 400:
            raise SecondBrainUnavailable(f"Memory listing failed HTTP {resp.status_code}")
        data = resp.json()
        return data if isinstance(data, list) else []

    def get_memory(self, memory_id: str) -> tuple[int, dict | None]:
        try:
            resp = self._http.get(f"/v1/memory/{memory_id}")
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        body = None
        try:
            body = resp.json()
        except ValueError:
            pass
        return resp.status_code, body

    def delete_memory(self, memory_id: str) -> bool:
        try:
            resp = self._http.delete(f"/v1/memory/{memory_id}")
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        return resp.status_code == 204

    # ---------------------------------------------------------------- documents
    def upload_document(
        self,
        path: str | Path,
        *,
        project_id: str | None = None,
        title: str | None = None,
        source: str | None = None,
    ) -> dict:
        """Upload PDF/DOCX/TXT/MD for server-side extraction + RAG indexing."""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(str(file_path))
        data = file_path.read_bytes()
        form: dict[str, str] = {}
        if project_id:
            form["project_id"] = project_id
        if title:
            form["title"] = title
        if source:
            form["source"] = source
        try:
            resp = self._http.post(
                "/v1/documents/upload",
                files={"file": (file_path.name, data)},
                data=form or None,
            )
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unreachable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code != 201:
            detail = resp.text[:200]
            raise SecondBrainUnavailable(f"Document upload failed HTTP {resp.status_code}: {detail}")
        return resp.json()

    def list_documents(self, limit: int = 50, project_id: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": max(1, min(int(limit), 500))}
        if project_id:
            params["project_id"] = project_id
        try:
            resp = self._http.get("/v1/documents", params=params)
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unavailable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        if resp.status_code >= 400:
            raise SecondBrainUnavailable(f"Document listing failed HTTP {resp.status_code}")
        data = resp.json()
        return data if isinstance(data, list) else []

    def delete_document(self, document_id: str) -> bool:
        try:
            resp = self._http.delete(f"/v1/documents/{document_id}")
        except httpx.HTTPError as exc:
            raise SecondBrainUnavailable(f"Second Brain unavailable: {exc}") from exc
        if resp.status_code in (401, 403):
            raise AuthFailure("Invalid or missing SECOND_BRAIN_API_KEY")
        return resp.status_code == 204

    # -------------------------------------------------------------------- sync
    def sync(self, max_items: int | None = None) -> SyncReport:
        report = SyncReport(remaining=self.store.pending_count())
        processed = 0
        while True:
            if max_items is not None and processed >= max_items:
                break
            batch = self.store.pending_batch(limit=min(25, max_items - processed if max_items else 25))
            if not batch:
                break
            progress = False
            for row in batch:
                processed += 1
                payload = json.loads(row["payload"])
                status_code, body = self._post_memory(payload)
                if status_code is None:
                    report.errors.append(f"item #{row['id']}: still unreachable")
                    continue  # keep others attemptable? stop to avoid hammering
                if 200 <= status_code < 300:
                    self.store.mark_write_done(int(row["id"]))
                    report.sent += 1
                    progress = True
                elif 400 <= status_code < 500:
                    detail = json.dumps(body)[:200] if body else f"HTTP {status_code}"
                    self.store.mark_write_failed(
                        int(row["id"]), f"permanent HTTP {status_code}: {detail}", permanent=True
                    )
                    report.permanent_failures += 1
                    progress = True
                else:
                    self.store.mark_write_failed(int(row["id"]), f"HTTP {status_code}", permanent=False)
                    report.errors.append(f"item #{row['id']}: HTTP {status_code}, kept in queue")
            report.remaining = self.store.pending_count()
            if not progress:
                break
        return report
