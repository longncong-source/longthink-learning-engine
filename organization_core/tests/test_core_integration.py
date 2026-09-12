"""Phase 08 tests: HTTP adapters, resilience, context propagation."""

from __future__ import annotations

import httpx
import pytest

from organization_core import integration as integ
from organization_core.adapters import AdapterBundle
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase08.sqlite3"))
    seed_dak(s)
    pid = new_id()
    now = utcnow_iso()
    s.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, 'Agent Zero', 'active',"
        " ?, ?, 0)",
        (pid, "zero08", now, now),
    )
    pos = s.query_one("SELECT id, department_id FROM positions WHERE code = ?",
                      ("DAK-TCHC-CV",))
    s.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, pos["id"], now, now),
    )
    yield s
    s.close()


@pytest.fixture()
def actor(store):
    row = store.query_one("SELECT id FROM persons WHERE code = 'zero08'")
    return row["id"]


def _cfg(handler, **overrides):
    params = {"base_url": "http://cores.test", "api_key": "k08",
              "backoff_base_seconds": 0.001, "max_retries": 2,
              "transport": httpx.MockTransport(handler)}
    params.update(overrides)
    return integ.CoreClientConfig(**params)


def _search_ok(request):
    assert request.headers["X-API-Key"] == "k08"
    assert request.headers["X-Correlation-ID"]
    return httpx.Response(200, json={
        "query": "q", "total": 1,
        "results": [{"id": "m1", "title": "Doc", "content": "body text",
                     "score": 0.9}]})


def test_mock_bundle_default():
    bundle = AdapterBundle.mocks()
    assert bundle.knowledge.search("q", {})["backend"] == "mock"
    assert bundle.intelligence.ask("q", {})["backend"] == "mock"
    built = integ.build_integration(
        integ.CoreClientConfig(base_url=""),
        integ.CoreClientConfig(base_url=""))
    assert isinstance(built.knowledge, integ.MockKnowledgeAdapter)


def test_search_maps_confirmed_contract(store, actor):
    client = integ.ResilientHttpClient(_cfg(_search_ok), "knowledge")
    adapter = integ.HttpKnowledgeAdapter(client)
    ctx = integ.build_outbound_context(store, actor, project_id="p08")
    out = adapter.search("hop dong", {**ctx, "top_k": 5})
    assert out["backend"] == "http" and out["total"] == 1
    assert out["results"][0]["ref_id"] == "m1"
    assert out["results"][0]["snippet"] == "body text"
    client.close()


def test_context_propagation_minimal(store, actor):
    captured = {}

    def handler(request):
        captured["body"] = request.read().decode()
        captured["headers"] = dict(request.headers)
        return _search_ok(request)

    import json as jsonlib

    client = integ.ResilientHttpClient(_cfg(handler), "knowledge")
    ctx = integ.build_outbound_context(store, actor, project_id="p08")
    assert ctx["actor_id"] == actor
    assert ctx["organization_id"]
    assert ctx["department_id"]
    assert ctx["project_id"] == "p08"
    assert ctx["correlation_id"]
    integ.HttpKnowledgeAdapter(client).search("q", ctx)
    client.close()
    body = jsonlib.loads(captured["body"])
    assert body["query"] == "q"
    assert body["context"]["actor_id"] == actor
    assert "full_name" not in captured["body"]
    assert "Agent Zero" not in captured["body"]
    assert "k08" not in captured["body"]  # key travels in header only
    assert captured["headers"]["x-correlation-id"]
    assert captured["headers"]["x-request-id"]


def test_safe_context_strips_secrets():
    safe = integ._safe_context({
        "actor_id": "a", "query": "q", "secret": "s3cr3t",
        "person": {"code": "p", "full_name": "Nobody"},
        "api_key": "k",
    })
    assert safe["actor_id"] == "a"
    assert safe["person"] == {"code": "p"}
    assert "secret" not in safe and "api_key" not in safe
    assert "query" not in safe


def test_timeout_structured_error():
    attempts = []

    def handler(request):
        attempts.append(1)
        raise httpx.ConnectTimeout("slow core")

    client = integ.ResilientHttpClient(
        _cfg(handler, max_retries=2), "knowledge")
    with pytest.raises(integ.CoreClientError) as exc_info:
        integ.HttpKnowledgeAdapter(client).search("q", {})
    assert exc_info.value.code == "timeout"
    assert exc_info.value.correlation_id
    assert len(attempts) == 3  # 1 initial + 2 retries
    client.close()


def test_retry_then_success():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, json={"error": "busy"})
        return _search_ok(request)

    client = integ.ResilientHttpClient(_cfg(handler), "knowledge")
    out = integ.HttpKnowledgeAdapter(client).search("q", {})
    assert out["total"] == 1
    assert len(calls) == 3
    client.close()


def test_no_retry_on_4xx():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(403, json={"error": "denied"})

    client = integ.ResilientHttpClient(_cfg(handler), "knowledge")
    with pytest.raises(integ.CoreClientError) as exc_info:
        integ.HttpKnowledgeAdapter(client).search("q", {})
    assert exc_info.value.code == "http"
    assert exc_info.value.status == 403
    assert len(calls) == 1
    client.close()


def test_invalid_response():
    client = integ.ResilientHttpClient(
        _cfg(lambda request: httpx.Response(200, json={"surprise": []})),
        "knowledge")
    with pytest.raises(integ.CoreClientError) as exc_info:
        integ.HttpKnowledgeAdapter(client).search("q", {})
    assert exc_info.value.code == "invalid_response"
    client.close()


def test_retrieve_requires_content():
    client = integ.ResilientHttpClient(
        _cfg(lambda request: httpx.Response(200, json={"id": "m1"})),
        "knowledge")
    with pytest.raises(integ.CoreClientError) as exc_info:
        integ.HttpKnowledgeAdapter(client).retrieve("m1")
    assert exc_info.value.code == "invalid_response"
    client.close()


def test_circuit_breaker_opens():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(500, json={"error": "down"})

    cfg = _cfg(handler, max_retries=0, circuit_threshold=2,
               circuit_cooldown_seconds=60)
    client = integ.ResilientHttpClient(cfg, "knowledge")
    adapter = integ.HttpKnowledgeAdapter(client)
    with pytest.raises(integ.CoreClientError):
        adapter.search("q", {})
    with pytest.raises(integ.CoreClientError):
        adapter.search("q", {})
    assert client.breaker.state == "open"
    with pytest.raises(integ.CoreClientError) as exc_info:
        adapter.search("q", {})
    assert exc_info.value.code == "circuit_open"
    assert len(calls) == 2  # third call rejected before transport
    client.close()


def test_intelligence_ask_plan_execute_mapping():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/process"):
            return httpx.Response(200, json={
                "answer": "a", "confidence": 0.7, "trace_id": "t1"})
        if request.url.path.endswith("/plan"):
            return httpx.Response(200, json={
                "plan_id": "p1", "steps": []})
        if request.url.path.endswith("/execute"):
            return httpx.Response(200, json={
                "plan_id": "p1", "results": []})
        return httpx.Response(404, json={})

    client = integ.ResilientHttpClient(_cfg(handler), "intelligence")
    intel = integ.HttpIntelligenceAdapter(client)
    assert intel.ask("q?", {})["trace_id"] == "t1"
    assert intel.plan("g", {})["plan_id"] == "p1"
    assert intel.execute("p1", {})["results"] == []
    assert intel.evaluate({"ok": True}, {})["evaluation"] == "a"
    assert paths[3].endswith("/process")  # evaluate reuses confirmed endpoint
    client.close()


def test_knowledge_candidate_mapping():
    def handler(request):
        assert request.url.path == "/v1/mid-brain/knowledge"
        return httpx.Response(200, json={"knowledge_id": "k1"})

    client = integ.ResilientHttpClient(_cfg(handler), "knowledge")
    out = integ.HttpKnowledgeAdapter(client).knowledge_candidate(
        {"content": "lesson", "kind": "lesson"})
    assert out["knowledge_id"] == "k1"
    client.close()


def test_unknown_actor_rejected(store):
    with pytest.raises(integ.CoreClientError):
        integ.build_outbound_context(store, "ghost")
