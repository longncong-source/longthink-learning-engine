"""Health endpoint contract + authentication behaviour (spec sections 8, 21)."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS, TEST_API_KEY


class TestHealthContract:
    def test_health_exact_body_no_auth(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_details_requires_auth(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/health/details")
        assert resp.status_code == 401
        body = resp.json()
        assert body["error"]["code"] == "unauthorized"

    def test_details_with_valid_key(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/health/details", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] in {"ok", "degraded"}
        assert body["storage"]["backend"].startswith("sqlite")
        assert body["embeddings"]["provider"] == "hash"
        assert body["embeddings"]["dimension"] == 64


class TestAuthentication:
    def test_missing_key_rejected_on_protected_route(self, client):  # type: ignore[no-untyped-def]
        resp = client.post("/v1/memory/search", json={"query": "anything"})
        assert resp.status_code == 401

    def test_invalid_key_rejected(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/memory/search",
            json={"query": "anything"},
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_bearer_token_accepted(self, client):  # type: ignore[no-untyped-def]
        resp = client.get(
            "/health/details", headers={"Authorization": f"Bearer {TEST_API_KEY}"}
        )
        assert resp.status_code == 200

    def test_x_api_key_accepted(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/memory/search",
            json={"query": "anything"},
            headers={"X-API-Key": TEST_API_KEY},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
