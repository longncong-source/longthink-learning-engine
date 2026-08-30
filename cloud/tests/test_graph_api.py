"""Graph API + UI mount tests: /v1/graph, /v1/graph/status, /ui static dashboard."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS
from cloud.tests.test_documents_api import SAMPLE_MD, _upload  # noqa: F401 - reuse helpers


class TestGraphEndpoint:
    def test_requires_auth(self, client):  # type: ignore[no-untyped-def]
        assert client.get("/v1/graph").status_code == 401
        assert client.get("/v1/graph/status").status_code == 401

    def test_empty_graph_structure(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/v1/graph", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["nodes"] == []
        assert body["links"] == []
        stats = body["stats"]
        assert stats["projects"] == 0
        assert stats["memories_returned"] == 0
        assert stats["documents"] == 0

    def test_project_and_memory_nodes_with_link(self, client):  # type: ignore[no-untyped-def]
        project = client.post(
            "/v1/projects", json={"name": "Graph Proj"}, headers=AUTH_HEADERS
        ).json()
        memory = client.post(
            "/v1/memory",
            json={"project_id": project["id"], "title": "graph seed",
                  "content": "knowledge node for graph test", "type": "lesson"},
            headers=AUTH_HEADERS,
        ).json()

        body = client.get("/v1/graph", headers=AUTH_HEADERS).json()
        ids = {n["id"] for n in body["nodes"]}
        assert f"p:{project['id']}" in ids
        assert f"m:{memory['memory']['id']}" in ids

        link = next(
            (lnk for lnk in body["links"]
             if lnk["source"] == f"m:{memory['memory']['id']}" and lnk["kind"] == "belongs_to"),
            None,
        )
        assert link is not None and link["target"] == f"p:{project['id']}"

        memory_node = next(n for n in body["nodes"] if n["id"] == f"m:{memory['memory']['id']}")
        assert memory_node["type"] == "lesson"
        assert memory_node["origin"] == "second-brain:api"

    def test_document_chunk_links(self, client):  # type: ignore[no-untyped-def]
        created = _upload(client).json()["document"]
        body = client.get("/v1/graph", headers=AUTH_HEADERS).json()

        doc_node = next(n for n in body["nodes"] if n["id"] == f"d:{created['id']}")
        assert doc_node["label"] == "Titled brief" or doc_node["filename"] == "brief.md"

        chunk_links = [lnk for lnk in body["links"] if lnk["kind"] == "chunk_of"
                       and lnk["target"] == f"d:{created['id']}"]
        assert chunk_links, "chunk memories must link to their document"

    def test_project_filter_scopes_graph(self, client):  # type: ignore[no-untyped-def]
        p1 = client.post("/v1/projects", json={"name": "Only This"}, headers=AUTH_HEADERS).json()
        client.post("/v1/projects", json={"name": "Other One"}, headers=AUTH_HEADERS).json()
        body = client.get("/v1/graph", params={"project_id": p1["id"]}, headers=AUTH_HEADERS).json()
        names = {n["label"] for n in body["nodes"] if n["kind"] == "project"}
        assert names == {"Only This"}

    def test_max_memories_caps_nodes(self, client):  # type: ignore[no-untyped-def]
        for i in range(5):
            client.post("/v1/memory", json={"title": f"cap {i}", "content": f"c{i}"},
                        headers=AUTH_HEADERS)
        body = client.get("/v1/graph", params={"max_memories": 2}, headers=AUTH_HEADERS).json()
        memories = [n for n in body["nodes"] if n["kind"] == "memory"]
        assert len(memories) <= 2


class TestGraphStatus:
    def test_status_shape_and_counts(self, client):  # type: ignore[no-untyped-def]
        client.post("/v1/memory", json={"title": "s", "content": "status probe"},
                    headers=AUTH_HEADERS)
        status = client.get("/v1/graph/status", headers=AUTH_HEADERS).json()
        assert status["backend"] == "sqlite"
        assert isinstance(status["uptime_seconds"], int)
        assert status["embedding"]["provider"] in {"hash", "ollama", "openai_compatible"}
        assert status["counts"]["memories"] >= 1
        assert status["counts"]["first_brain_writes"] >= 0
        assert "semantic" in status["counts"]["memories_by_type"]

    def test_embedding_probe_never_raises(self, client):  # type: ignore[no-untyped-def]
        status = client.get("/v1/graph/status", headers=AUTH_HEADERS).json()
        assert isinstance(status["embedding"]["reachable"], bool)


class TestDashboardMount:
    def test_ui_index_served(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/ui/")
        assert resp.status_code == 200
        assert "First" in resp.text and "Second Brain" in resp.text

    def test_ui_assets_served(self, client):  # type: ignore[no-untyped-def]
        for asset in ("/ui/styles.css", "/ui/app.js", "/ui/graph.js"):
            assert client.get(asset).status_code == 200

    def test_ui_traffic_not_audited(self, client):  # type: ignore[no-untyped-def]
        before = client.get("/v1/admin/audit?limit=200", headers=AUTH_HEADERS).json()["events"]
        ui_hits_before = sum(1 for e in before if (e.get("path") or "").startswith("/ui"))
        client.get("/ui/")
        after = client.get("/v1/admin/audit?limit=200", headers=AUTH_HEADERS).json()["events"]
        ui_hits_after = sum(1 for e in after if (e.get("path") or "").startswith("/ui"))
        assert ui_hits_after == ui_hits_before == 0


class TestCorsForCrossHostDashboard:
    def test_preflight_and_origin_header(self, client):  # type: ignore[no-untyped-def]
        preflight = client.options(
            "/v1/documents/upload",
            headers={
                "Origin": "http://127.0.0.1:8100",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
        assert preflight.status_code in {200, 204}
        assert preflight.headers["access-control-allow-origin"] == "*"

        simple = client.get("/health", headers={"Origin": "https://brain.example.com"})
        assert simple.headers["access-control-allow-origin"] == "*"
