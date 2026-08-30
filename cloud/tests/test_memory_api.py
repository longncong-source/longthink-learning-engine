"""Memory API integration tests over SQLite backend: CRUD, search, dedupe, redaction,
filters, failure modes (spec sections 8-13, 20, 26)."""

from __future__ import annotations

import uuid

import pytest

from cloud.app.errors import UpstreamUnavailableError
from cloud.tests.conftest import AUTH_HEADERS


def _memory_payload(**overrides) -> dict:
    base = {
        "title": "Vendor A mechanical drawing delay",
        "content": "Vendor A delayed mechanical drawing approval by 21 days.",
        "type": "episodic",
        "importance": 0.75,
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


class TestWritePipeline:
    def test_write_returns_memory(self, client):  # type: ignore[no-untyped-def]
        resp = client.post("/v1/memory", json=_memory_payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 201
        body = resp.json()
        assert body["deduplicated"] is False
        assert body["redaction_count"] == 0
        memory = body["memory"]
        assert memory["id"]
        assert memory["type"] == "episodic"
        assert memory["importance"] == pytest.approx(0.75)
        assert memory["created_at"]

    def test_write_redacts_secrets(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/memory",
            json=_memory_payload(
                title="Incident report",
                content="The leaked key sk-proj-abcdefgh123456789012 was revoked. password=hunter2secret",
            ),
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["redaction_count"] >= 2
        stored = body["memory"]["content"]
        assert "sk-proj-abcdefgh123456789012" not in stored
        assert "hunter2secret" not in stored
        assert "[REDACTED_API_KEY]" in stored

    def test_dedupe_merges_instead_of_duplicate(self, client):  # type: ignore[no-untyped-def]
        first = client.post("/v1/memory", json=_memory_payload(), headers=AUTH_HEADERS).json()
        second = client.post(
            "/v1/memory",
            json=_memory_payload(importance=0.95),
            headers=AUTH_HEADERS,
        ).json()
        assert second["deduplicated"] is True
        assert second["memory"]["id"] == first["memory"]["id"]
        assert second["memory"]["importance"] == pytest.approx(0.95)

    def test_unknown_project_rejected(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/memory",
            json=_memory_payload(project_id=str(uuid.uuid4())),
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 404

    def test_embedding_failure_is_meaningful_503(self, client, monkeypatch):  # type: ignore[no-untyped-def]
        def boom(text, settings=None):
            raise UpstreamUnavailableError("embedding server down")

        monkeypatch.setattr("cloud.app.services.memory_service.embed_text", boom)
        resp = client.post("/v1/memory", json=_memory_payload(), headers=AUTH_HEADERS)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "upstream_unavailable"

    def test_storage_failure_is_meaningful_503(self, client, monkeypatch):  # type: ignore[no-untyped-def]
        from cloud.app.errors import RepositoryError

        class ExplodingRepo:
            backend_name = "exploding"

            def get_memory(self, memory_id):
                raise RepositoryError("simulated disk failure")

        monkeypatch.setattr(
            "cloud.app.routers.memories.get_repository", lambda *a, **kw: ExplodingRepo()
        )
        resp = client.get(f"/v1/memory/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 503
        assert resp.json()["error"]["code"] == "storage_unavailable"


class TestValidation:
    @pytest.mark.parametrize(
        "payload_field,bad_value",
        [
            ("title", ""),
            ("content", ""),
            ("type", "not-a-type"),
            ("importance", 1.5),
            ("confidence", -0.1),
        ],
    )
    def test_invalid_fields_422(self, client, payload_field, bad_value):  # type: ignore[no-untyped-def]
        payload = _memory_payload(**{payload_field: bad_value})
        resp = client.post("/v1/memory", json=payload, headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_empty_search_query_422(self, client):  # type: ignore[no-untyped-def]
        resp = client.post("/v1/memory/search", json={"query": ""}, headers=AUTH_HEADERS)
        assert resp.status_code == 422

    def test_error_body_shape(self, client):  # type: ignore[no-untyped-def]
        resp = client.post("/v1/memory", json=_memory_payload(importance=42), headers=AUTH_HEADERS)
        assert resp.status_code == 422
        body = resp.json()
        assert body["error"]["code"] == "validation_error"


class TestSearchPipeline:
    def _seed(self, client):  # type: ignore[no-untyped-def]
        r1 = client.post(
            "/v1/memory",
            json=_memory_payload(),
            headers=AUTH_HEADERS,
        ).json()["memory"]
        r2 = client.post(
            "/v1/memory",
            json={
                "title": "Friday lunch menu",
                "content": "Office pizza day moved to Friday.",
                "type": "semantic",
                "importance": 0.3,
            },
            headers=AUTH_HEADERS,
        ).json()["memory"]
        return r1, r2

    def test_relevant_memory_ranks_first(self, client):  # type: ignore[no-untyped-def]
        relevant, irrelevant = self._seed(client)
        resp = client.post(
            "/v1/memory/search",
            json={"query": "mechanical drawing approval delay"},
            headers=AUTH_HEADERS,
        )
        assert resp.status_code == 200
        results = resp.json()["results"]
        assert results, "expected non-empty results"
        assert results[0]["id"] == relevant["id"]
        assert results[0]["score"] > [r for r in results if r["id"] == irrelevant["id"]][0]["score"]

    def test_scores_breakdown_present(self, client):  # type: ignore[no-untyped-def]
        self._seed(client)
        resp = client.post(
            "/v1/memory/search",
            json={"query": "mechanical drawing delay"},
            headers=AUTH_HEADERS,
        )
        scores = resp.json()["results"][0]["scores"]
        for key in ("semantic", "keyword", "importance", "recency"):
            assert key in scores
            assert 0.0 <= scores[key] <= 1.0

    def test_type_filter(self, client):  # type: ignore[no-untyped-def]
        relevant, _ = self._seed(client)
        resp = client.post(
            "/v1/memory/search",
            json={"query": "drawing delay", "filters": {"type": "episodic"}},
            headers=AUTH_HEADERS,
        )
        ids = [r["id"] for r in resp.json()["results"]]
        assert relevant["id"] in ids

    def test_min_importance_filter(self, client):  # type: ignore[no-untyped-def]
        _, irrelevant = self._seed(client)
        resp = client.post(
            "/v1/memory/search",
            json={"query": "lunch pizza friday", "filters": {"min_importance": 0.6}},
            headers=AUTH_HEADERS,
        )
        ids = [r["id"] for r in resp.json()["results"]]
        assert irrelevant["id"] not in ids

    def test_metadata_filter(self, client):  # type: ignore[no-untyped-def]
        client.post(
            "/v1/memory",
            json=_memory_payload(metadata={"vendor": "A"}),
            headers=AUTH_HEADERS,
        )
        hit = client.post(
            "/v1/memory/search",
            json={"query": "drawing delay", "filters": {"metadata": {"vendor": "A"}}},
            headers=AUTH_HEADERS,
        )
        miss = client.post(
            "/v1/memory/search",
            json={"query": "drawing delay", "filters": {"metadata": {"vendor": "B"}}},
            headers=AUTH_HEADERS,
        )
        assert hit.json()["total"] >= 1
        assert miss.json()["total"] == 0

    def test_top_k_limit_respected(self, client):  # type: ignore[no-untyped-def]
        for i in range(5):
            client.post(
                "/v1/memory",
                json=_memory_payload(title=f"Delay note {i}", content=f"Drawing delay case {i}"),
                headers=AUTH_HEADERS,
            )
        resp = client.post(
            "/v1/memory/search",
            json={"query": "drawing delay", "top_k": 2},
            headers=AUTH_HEADERS,
        )
        assert len(resp.json()["results"]) <= 2


class TestCrudById:
    def test_get_and_delete_flow(self, client):  # type: ignore[no-untyped-def]
        created = client.post("/v1/memory", json=_memory_payload(), headers=AUTH_HEADERS).json()["memory"]

        got = client.get(f"/v1/memory/{created['id']}", headers=AUTH_HEADERS)
        assert got.status_code == 200
        assert got.json()["title"] == created["title"]

        deleted = client.delete(f"/v1/memory/{created['id']}", headers=AUTH_HEADERS)
        assert deleted.status_code == 204

        gone = client.get(f"/v1/memory/{created['id']}", headers=AUTH_HEADERS)
        assert gone.status_code == 404

    def test_get_unknown_404(self, client):  # type: ignore[no-untyped-def]
        resp = client.get(f"/v1/memory/{uuid.uuid4()}", headers=AUTH_HEADERS)
        assert resp.status_code == 404
