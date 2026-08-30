"""Admin endpoints tests: persistent audit trail + Prometheus metrics (sections 25/41)."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS


def _write_memory(client):  # type: ignore[no-untyped-def]
    resp = client.post(
        "/v1/memory",
        json={"title": "audit probe", "content": "checking audit trail", "type": "semantic"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 201
    return resp.json()


class TestAuditTrail:
    def test_http_and_domain_events_recorded(self, client):  # type: ignore[no-untyped-def]
        _write_memory(client)
        events = client.get("/v1/admin/audit?limit=100", headers=AUTH_HEADERS).json()["events"]
        assert events, "expected audit events"

        kinds = {e["kind"] for e in events}
        assert "http" in kinds
        assert "memory.write" in kinds

        http_event = next(e for e in events if e["kind"] == "http" and e["path"] == "/v1/memory")
        assert http_event["status"] == 201
        assert http_event["method"] == "POST"
        assert http_event["duration_ms"] >= 0
        assert http_event["request_id"]

        write_event = next(e for e in events if e["kind"] == "memory.write")
        assert write_event["result_count"] == 1
        assert write_event["detail"]["deduplicated"] is False

    def test_health_is_not_audited(self, client):  # type: ignore[no-untyped-def]
        client.get("/health")
        client.get("/health")
        events = client.get("/v1/admin/audit", headers=AUTH_HEADERS).json()["events"]
        assert all(e.get("path") != "/health" for e in events)

    def test_admin_requires_auth(self, client):  # type: ignore[no-untyped-def]
        assert client.get("/v1/admin/audit").status_code == 401
        assert client.get("/v1/admin/metrics").status_code == 401

    def test_audit_outage_never_breaks_requests(self, client, monkeypatch):  # type: ignore[no-untyped-def]
        class BrokenAuditRepo:
            backend_name = "broken-audit"

            def record_audit(self, event):
                raise RuntimeError("audit storage down")

        monkeypatch.setattr(
            "cloud.app.services.audit_service.get_repository",
            lambda *a, **kw: BrokenAuditRepo(),
        )
        resp = client.post("/v1/memory", json={"title": "t", "content": "c"}, headers=AUTH_HEADERS)
        assert resp.status_code == 201  # request survives the audit outage

        body = resp.json()
        assert body["memory"]["id"]
        # failure was counted instead of crashing
        metrics_text = client.get("/v1/admin/metrics", headers=AUTH_HEADERS).text
        assert "fsb_audit_write_failures_total" in metrics_text


class TestMetricsEndpoint:
    def test_counters_after_traffic(self, client):  # type: ignore[no-untyped-def]
        _write_memory(client)
        client.post("/v1/memory/search", json={"query": "audit"}, headers=AUTH_HEADERS)

        resp = client.get("/v1/admin/metrics", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        body = resp.text
        assert "# TYPE fsb_http_requests_total counter" in body
        assert "fsb_http_requests_total{" in body
        assert "fsb_memory_writes_total{" in body
        assert 'result="created"' in body
        assert "fsb_memory_searches_total 1" in body
        assert 'fsb_build_info{backend="sqlite' in body
        assert "fsb_uptime_seconds" in body

    def test_unit_snapshot_formatting(self):  # type: ignore[no-untyped-def]
        from cloud.app import metrics

        metrics.reset()
        metrics.inc("fsb_unit_demo_total", {"code": "200"}, value=2)
        snapshot = metrics.snapshot(backend="unit-test")
        assert "# TYPE fsb_unit_demo_total counter" in snapshot
        assert 'fsb_unit_demo_total{code="200"} 2' in snapshot
        assert 'fsb_build_info{backend="unit-test"} 1' in snapshot

    def test_rate_limited_requests_are_counted(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        from cloud.tests.conftest import TEST_API_KEY, configure_test_env

        configure_test_env(monkeypatch, tmp_path, RATE_LIMIT_PER_MINUTE="1")

        from cloud.app import main as main_module
        from cloud.app import metrics
        from cloud.app.config import get_settings
        from cloud.app.db import get_repository, reset_repository
        from cloud.app.embeddings import reset_embedding_provider

        get_settings.cache_clear()
        reset_repository()
        reset_embedding_provider()
        app = main_module.create_app()
        get_repository().init_schema()

        with TestClient(app) as http:
            http.get("/health/details", headers={"X-API-Key": TEST_API_KEY})
            limited = http.get("/health/details", headers={"X-API-Key": TEST_API_KEY})
            assert limited.status_code == 429
            snapshot = metrics.snapshot(backend="sqlite")
            get_settings.cache_clear()
            reset_repository()
            reset_embedding_provider()

        assert 'fsb_http_requests_total{code="429"} 1' in snapshot
        assert 'fsb_http_requests_total{code="200"} 1' in snapshot
