"""Tests for the memory listing endpoint used by `brain memory list`."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS


class TestMemoryList:
    def _seed(self, client):  # type: ignore[no-untyped-def]
        payloads = [
            {"title": "Episodic event", "content": "Vendor delayed 21 days.", "type": "episodic"},
            {"title": "Semantic fact", "content": "Project uses FIDIC.", "type": "semantic"},
        ]
        ids = []
        for p in payloads:
            resp = client.post("/v1/memory", json=p, headers=AUTH_HEADERS)
            assert resp.status_code == 201
            ids.append(resp.json()["memory"]["id"])
        return ids

    def test_list_all(self, client):  # type: ignore[no-untyped-def]
        self._seed(client)
        resp = client.get("/v1/memory", params={"limit": 10}, headers=AUTH_HEADERS)
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) >= 2

    def test_list_filter_by_type(self, client):  # type: ignore[no-untyped-def]
        self._seed(client)
        resp = client.get("/v1/memory", params={"limit": 50, "type": "episodic"}, headers=AUTH_HEADERS)
        rows = resp.json()
        assert rows and all(r["type"] == "episodic" for r in rows)

    def test_list_requires_auth(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/v1/memory")
        assert resp.status_code == 401
