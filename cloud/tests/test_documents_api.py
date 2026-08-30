"""Document API integration tests: upload -> chunk-mirror -> RAG search -> delete cascade."""

from __future__ import annotations

import uuid

from cloud.tests.conftest import AUTH_HEADERS

SAMPLE_MD = (
    b"# Mechanical Package Brief\n\n"
    b"The mechanical package experienced a 21 day approval delay caused by vendor A drawings.\n\n"
    b"## Safety rules\n\n"
    b"All cryogenic areas require two-person verification before valve operation.\n\n"
    b"## Commercial\n\n"
    b"Liquidated damages apply at 0.5 percent per week of delay."
)


def _upload(client, name="brief.md", data=SAMPLE_MD, **form):  # type: ignore[no-untyped-def]
    files = {"file": (name, data, "text/markdown")}
    resp = client.post("/v1/documents/upload", files=files, data=form or None, headers=AUTH_HEADERS)
    return resp


class TestIngestAndRag:
    def test_upload_returns_chunks(self, client):  # type: ignore[no-untyped-def]
        resp = _upload(client)
        assert resp.status_code == 201
        body = resp.json()
        # sample doc fits inside one 1200-char chunk -> exactly one mirrored memory
        assert body["chunks_indexed"] == 1
        doc = body["document"]
        assert doc["filename"] == "brief.md"
        assert doc["mime_type"] == "text/markdown"

    def test_long_document_yields_multiple_chunks(self, client):  # type: ignore[no-untyped-def]
        section = (
            "Procurement notes paragraph. " * 12
            + "\n\nVendor drawings must be reviewed before purchase orders are issued.\n\n"
        )
        long_md = ("# Long brief\n\n" + section * 8).encode("utf-8")
        resp = _upload(client, name="long.md", data=long_md)
        assert resp.status_code == 201
        body = resp.json()
        assert body["chunks_indexed"] >= 3

    def test_chunks_searchable_with_citation_metadata(self, client):  # type: ignore[no-untyped-def]
        created = _upload(client).json()["document"]
        resp = client.post(
            "/v1/memory/search",
            json={"query": "two person verification cryogenic valve", "top_k": 5,
                  "filters": {"type": "document"}},
            headers=AUTH_HEADERS,
        )
        results = resp.json()["results"]
        hit = next((r for r in results if r["metadata"].get("document_id") == created["id"]), None)
        assert hit is not None
        assert hit["metadata"]["filename"] == "brief.md"
        assert hit["metadata"]["page"] == 1
        assert "memory_id" not in hit["metadata"]

    def test_delete_removes_document_and_mirrors(self, client):  # type: ignore[no-untyped-def]
        created = _upload(client).json()["document"]
        query = {"query": "liquidated damages 0.5 percent", "top_k": 10}
        before = client.post("/v1/memory/search", json=query, headers=AUTH_HEADERS).json()
        assert any(r["metadata"].get("document_id") == created["id"] for r in before["results"])

        deleted = client.delete(f"/v1/documents/{created['id']}", headers=AUTH_HEADERS)
        assert deleted.status_code == 204

        after = client.post("/v1/memory/search", json=query, headers=AUTH_HEADERS).json()
        assert not any(r["metadata"].get("document_id") == created["id"] for r in after["results"])

        gone = client.delete(f"/v1/documents/{created['id']}", headers=AUTH_HEADERS)
        assert gone.status_code == 404


class TestUploadGuards:
    def test_unsupported_extension_415(self, client):  # type: ignore[no-untyped-def]
        resp = _upload(client, name="evil.exe", data=b"MZ fake")
        assert resp.status_code == 415
        assert resp.json()["error"]["code"] == "unsupported_media_type"

    def test_unknown_project_404(self, client):  # type: ignore[no-untyped-def]
        resp = _upload(client, project_id=str(uuid.uuid4()))
        assert resp.status_code == 404

    def test_oversize_413(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]

        from fastapi.testclient import TestClient

        from cloud.tests.conftest import TEST_API_KEY, configure_test_env

        configure_test_env(monkeypatch, tmp_path, MAX_UPLOAD_MB="0")

        from cloud.app import main as main_module
        from cloud.app.config import get_settings
        from cloud.app.db import get_repository, reset_repository
        from cloud.app.embeddings import reset_embedding_provider

        get_settings.cache_clear()
        reset_repository()
        reset_embedding_provider()
        app = main_module.create_app()
        get_repository().init_schema()

        with TestClient(app) as http:
            resp = http.post(
                "/v1/documents/upload",
                files={"file": ("tiny.md", b"some content here", "text/markdown")},
                headers={"X-API-Key": TEST_API_KEY},
            )
            get_settings.cache_clear()
            reset_repository()
            reset_embedding_provider()
        assert resp.status_code == 413

    def test_requires_auth(self, client):  # type: ignore[no-untyped-def]
        files = {"file": ("x.md", b"data", "text/markdown")}
        resp = client.post("/v1/documents/upload", files=files)
        assert resp.status_code == 401


class TestListAndGet:
    def test_list_and_get(self, client):  # type: ignore[no-untyped-def]
        created = _upload(client, title="Titled brief").json()["document"]
        listed = client.get("/v1/documents", params={"limit": 50}, headers=AUTH_HEADERS).json()
        match = [d for d in listed if d["id"] == created["id"]]
        assert match and match[0]["title"] == "Titled brief"

        fetched = client.get(f"/v1/documents/{created['id']}", headers=AUTH_HEADERS)
        assert fetched.status_code == 200
