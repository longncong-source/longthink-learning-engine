"""Phase 12 tests: metrics, tracing headers, readiness, log redaction."""

from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from organization_core import integration as integ
from organization_core import observability as obs
from organization_core.api import create_org_app
from organization_core.auth import authorize
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase12.sqlite3"))
    seed_dak(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    obs.reset()
    return TestClient(create_org_app(store))


def test_request_id_and_counts(client):
    obs.reset()
    first = client.get("/health")
    assert first.headers["X-Request-ID"]
    second = client.get("/health", headers={"X-Request-ID": "fixed-1"})
    assert second.headers["X-Request-ID"] == "fixed-1"
    snap = client.get("/v1/metrics").json()
    counts = [v for k, v in snap["counters"].items()
              if k.startswith("org_request_count")]
    assert sum(counts) >= 2
    assert any("org_request_latency_seconds" in k
               for k in snap["latencies"])


def test_authorization_denied_metric(store):
    obs.reset()
    result = authorize(store, actor_person_id="ghost", action="READ",
                       resource="document")
    assert result.allow is False
    snap = obs.snapshot()
    assert snap["counters"].get("org_authorization_denied_total", 0) >= 1


def test_ready_healthy_and_unhealthy(client, store):
    assert client.get("/ready").json()["ready"] is True
    store.drop_all()  # simulate a degraded backend
    resp = client.get("/ready")
    assert resp.status_code == 503
    assert resp.json()["ready"] is False


def test_log_redaction():
    formatter = obs.RedactingFormatter()
    record = logging.LogRecord("org", logging.INFO, __file__, 1,
                               "key sk-proj-abc123XYZ q", None, None)
    out = formatter.format(record)
    assert "sk-proj-abc123XYZ" not in out
    assert "[REDACTED]" in out
    logger = obs.get_logger("org-test-12")
    assert logger.handlers  # singleton wiring, no duplicate handlers
    assert len(logger.handlers) == len(obs.get_logger("org-test-12").handlers)


def test_external_latency_observed():
    obs.reset()

    def handler(request):
        return httpx.Response(200, json={
            "query": "q", "total": 0, "results": []})

    cfg = integ.CoreClientConfig(
        base_url="http://cores.test", backoff_base_seconds=0.001,
        transport=httpx.MockTransport(handler))
    client = integ.ResilientHttpClient(cfg, "knowledge")
    integ.HttpKnowledgeAdapter(client).search("q", {})
    client.close()
    snap = obs.snapshot()
    keys = [k for k in snap["latencies"]
            if k.startswith("org_external_core_latency_seconds")]
    assert keys and snap["latencies"][keys[0]]["count"] >= 1


def test_metrics_snapshot_shape(client):
    snap = client.get("/v1/metrics").json()
    assert set(snap) == {"counters", "latencies"}
