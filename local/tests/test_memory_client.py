"""SecondBrainClient tests: policy gate, redaction, queue+sync, cache (spec sections 11/19/20/23/24)."""

from __future__ import annotations

import json

import httpx
import pytest

from local.config import BrainSettings
from local.local_store import LocalStore
from local.memory_client import AuthFailure, SecondBrainClient, SecondBrainUnavailable


def _make_settings(**over) -> BrainSettings:
    base = {
        "second_brain_url": "http://testserver",
        "second_brain_api_key": "good-key",
        "data_policy": "selective",
        "memory_top_k": 8,
        "cache_ttl_seconds": 600,
        "request_timeout_seconds": 5.0,
        "local_data_dir": "unused",
    }
    base.update(over)
    return BrainSettings(**base)


def _make_client(handler, tmp_path, settings=None) -> SecondBrainClient:
    store = LocalStore(tmp_path / "local.db")
    client = SecondBrainClient(
        settings=settings or _make_settings(),
        store=store,
        transport=httpx.MockTransport(handler),
    )
    return client


SEARCH_BODY = {
    "query": "delay",
    "total": 1,
    "results": [
        {
            "id": "m-1",
            "type": "lesson",
            "title": "Review first",
            "content": "Review drawings before procurement.",
            "score": 0.9,
            "scores": {"semantic": 0.9, "keyword": 0.8, "importance": 0.7, "recency": 1.0},
            "metadata": {},
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
    ],
}


class StateHandler:
    """Mock transport behaviour container. Tests may monkeypatch .handle."""

    def __init__(self) -> None:
        self.calls = 0
        self.mode = "up"
        self.write_status = 201
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        return self.handle(request)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.requests.append(request)
        if self.mode == "down":
            raise httpx.ConnectError("connection refused", request=request)
        if request.headers.get("x-api-key") != "good-key":
            return httpx.Response(401, json={"error": {"code": "unauthorized", "message": "bad key"}})
        path = request.url.path
        method = request.method
        if method == "GET" and path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if method == "GET" and path == "/health/details":
            return httpx.Response(200, json={"status": "ok", "storage": {"backend": "sqlite"}})
        if method == "POST" and path == "/v1/memory":
            if self.write_status != 201:
                return httpx.Response(self.write_status, json={"error": {"code": "validation_error", "message": "bad"}})
            return httpx.Response(201, json={"memory": {"id": "mem-123"}, "deduplicated": False, "redaction_count": 0})
        if method == "POST" and path == "/v1/memory/search":
            return httpx.Response(200, json=SEARCH_BODY)
        if method == "GET" and path == "/v1/projects":
            return httpx.Response(200, json=[{"id": "p-1", "name": "LNG Project"}])
        if method == "POST" and path == "/v1/projects":
            body = json.loads(request.content.decode())
            return httpx.Response(201, json={"id": "p-new", "name": body.get("name")})
        return httpx.Response(404, json={"error": {"code": "not_found", "message": path}})


class TestWritePaths:
    def test_stored_write(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)
        outcome = client.write_memory(title="t", content="c", type="lesson")
        assert outcome.status == "stored"
        assert outcome.memory_id == "mem-123"

    def test_redaction_before_send(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)
        outcome = client.write_memory(title="leak", content="key sk-proj-abcdefgh123456789 here")
        sent_body = json.loads(state.requests[-1].content.decode())
        assert outcome.redaction_count >= 1
        assert "sk-proj-abcdefgh123456789" not in sent_body["content"]
        assert "[REDACTED_API_KEY]" in sent_body["content"]

    def test_offline_queues_then_sync_sends(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)

        state.mode = "down"
        outcome = client.write_memory(title="offline", content="queued while cloud down")
        assert outcome.status == "queued"
        assert client.store.pending_count() == 1

        state.mode = "up"
        report = client.sync()
        assert report.sent == 1
        assert report.remaining == 0
        assert client.store.pending_count() == 0

    def test_auth_failure_does_not_queue(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()

        def make_bad(_settings):
            return None

        client = _make_client(
            state,
            tmp_path,
            settings=_make_settings(second_brain_api_key="wrong"),
        )
        with pytest.raises(AuthFailure):
            client.search("anything")
        with pytest.raises(AuthFailure):
            client.write_memory(title="t", content="c")
        assert client.store.pending_count() == 0

    def test_local_only_policy_never_sends(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path, settings=_make_settings(data_policy="local_only"))
        outcome = client.write_memory(title="private", content="stays on laptop")
        assert outcome.status == "skipped_policy"
        assert state.calls == 0
        notes = client.store.list_notes()
        assert any(n["kind"] == "local_only_memory" for n in notes)

    def test_rejected_422_reported_not_queued(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        state.write_status = 422
        client = _make_client(state, tmp_path)
        outcome = client.write_memory(title="", content="")  # empty strings redact to ""
        assert outcome.status == "rejected"
        assert client.store.pending_count() == 0


class TestSyncFailureModes:
    def test_permanent_4xx_dropped_during_sync(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)
        state.mode = "down"
        client.write_memory(title="will be rejected later", content="x")
        state.mode = "up"
        state.write_status = 400
        report = client.sync()
        assert report.permanent_failures == 1
        assert report.remaining == 0


class TestSearchCache:
    def test_second_identical_search_is_cached(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)
        first = client.search("vendor delay")
        second = client.search("vendor delay")
        assert "_cache" not in first
        assert second.get("_cache") == "hit"
        search_calls = [
            r for r in state.requests if r.url.path == "/v1/memory/search"
        ]
        assert len(search_calls) == 1

    def test_unreachable_raises(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        state.mode = "down"
        client = _make_client(state, tmp_path)
        with pytest.raises(SecondBrainUnavailable):
            client.search("anything")


class TestProjects:
    def test_ensure_project_finds_existing_without_post(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path)
        project_id = client.ensure_project("lng project")  # case-insensitive match
        assert project_id == "p-1"
        posts = [r for r in state.requests if r.method == "POST" and r.url.path == "/v1/projects"]
        assert posts == []

    def test_health_none_when_down(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        state.mode = "down"
        client = _make_client(state, tmp_path)
        assert client.health() is None
