"""ONE VECTOR PLATFORM: 8 logical domains mapped from memory types + knowledge_type."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS


class TestKnowledgeDomains:
    def test_platform_shape(self, client):  # type: ignore[no-untyped-def]
        resp = client.get("/v1/memory/knowledge-domains", headers=AUTH_HEADERS)
        assert resp.status_code == 200
        body = resp.json()
        assert body["backend"] in ("sqlite", "postgres", "postgres+pgvector")
        assert body["embedding_dimension"] > 0
        labels = [d["label"] for d in body["domains"]]
        assert labels == ["PROJECT", "ENGINEERING", "STANDARD", "CONTRACT",
                          "METHOD", "SITE", "DOCUMENT", "LESSON"]
        assert all(d["status"] in ("active", "empty") for d in body["domains"])
        total = sum(d["count"] for d in body["domains"]) + body["unclassified"]["count"]
        assert total == body["total_memories"]

    def test_document_maps_to_document_domain(self, client):  # type: ignore[no-untyped-def]
        files = {"file": ("dom.md", b"# Domain map test\n\nPump alignment content here.\n", "text/markdown")}
        up = client.post("/v1/documents/upload", files=files, headers=AUTH_HEADERS)
        assert up.status_code == 201
        body = client.get("/v1/memory/knowledge-domains", headers=AUTH_HEADERS).json()
        doc = next(d for d in body["domains"] if d["key"] == "document")
        assert doc["status"] == "active"
        assert doc["count"] >= 1
        assert doc["memory_types"].get("document", 0) >= 1

    def test_knowledge_type_wins_over_memory_type(self, client):  # type: ignore[no-untyped-def]
        from cloud.app.db import MemoryRecord, get_repository

        repo = get_repository()
        repo.create_memory(MemoryRecord(
            type="semantic", title="kt test", content="kt Engineering content",
            metadata={"knowledge_type": "engineering"},
            embedding=[0.1] * 64,
        ))
        body = client.get("/v1/memory/knowledge-domains", headers=AUTH_HEADERS).json()
        eng = next(d for d in body["domains"] if d["key"] == "engineering")
        assert eng["count"] >= 1
        total = sum(d["count"] for d in body["domains"]) + body["unclassified"]["count"]
        assert total == body["total_memories"]
