"""Folder watcher tests: register -> scan NEW -> UNCHANGED -> MODIFIED -> DELETED."""

from __future__ import annotations

from cloud.tests.conftest import AUTH_HEADERS

DOC_A = b"# Site report A\n\nConcrete pour at block B completed without issues.\n"
DOC_B = b"# Method statement\n\nHVAC duct installation follows quadrants one to four.\n"


def _register(client, path):  # type: ignore[no-untyped-def]
    return client.post("/v1/documents/watch", json={"path": str(path)}, headers=AUTH_HEADERS)


class TestWatcher:
    def test_register_rejects_non_directory(self, client, tmp_path):  # type: ignore[no-untyped-def]
        resp = _register(client, tmp_path / "nope")
        assert resp.status_code in (400, 422)

    def test_incremental_lifecycle(self, client, tmp_path):  # type: ignore[no-untyped-def]
        watch_dir = tmp_path / "knowledge"
        watch_dir.mkdir()
        (watch_dir / "a.md").write_bytes(DOC_A)
        (watch_dir / "b.md").write_bytes(DOC_B)

        assert _register(client, watch_dir).status_code == 201

        first = client.post("/v1/documents/watch/scan", headers=AUTH_HEADERS)
        assert first.status_code == 200
        body = first.json()
        assert body["new"] == 2
        assert body["unchanged"] == 0

        docs = client.get("/v1/documents", headers=AUTH_HEADERS).json()
        assert len(docs) == 2
        assert all(d["source"].startswith("watch:") for d in docs)

        # UNCHANGED: second scan must not create anything
        second = client.post("/v1/documents/watch/scan", headers=AUTH_HEADERS).json()
        assert second["new"] == 0
        assert second["unchanged"] == 2
        assert len(client.get("/v1/documents", headers=AUTH_HEADERS).json()) == 2

        # MODIFIED: touch one file -> re-ingest replaces old doc
        (watch_dir / "a.md").write_bytes(DOC_A + b"\nExtra line added later.\n")
        third = client.post("/v1/documents/watch/scan", headers=AUTH_HEADERS).json()
        assert third["modified"] == 1
        assert third["unchanged"] == 1
        assert len(client.get("/v1/documents", headers=AUTH_HEADERS).json()) == 2

        # DELETED: remove file -> doc cascade removed
        (watch_dir / "b.md").unlink()
        fourth = client.post("/v1/documents/watch/scan", headers=AUTH_HEADERS).json()
        assert fourth["deleted"] == 1
        remaining = client.get("/v1/documents", headers=AUTH_HEADERS).json()
        assert len(remaining) == 1
        assert remaining[0]["filename"] == "a.md"

    def test_status_and_unregister(self, client, tmp_path):  # type: ignore[no-untyped-def]
        watch_dir = tmp_path / "w"
        watch_dir.mkdir()
        _register(client, watch_dir)
        st = client.get("/v1/documents/watch", headers=AUTH_HEADERS).json()
        assert any(f["path"].endswith("w") for f in st["folders"])
        assert st["poll_seconds"] >= 10

        resp = client.delete(
            "/v1/documents/watch", params={"path": str(watch_dir)}, headers=AUTH_HEADERS
        )
        assert resp.status_code == 204
        st2 = client.get("/v1/documents/watch", headers=AUTH_HEADERS).json()
        assert st2["folders"] == []
