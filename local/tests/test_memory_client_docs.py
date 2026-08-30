"""SecondBrainClient document methods against MockTransport."""

from __future__ import annotations

import httpx
import pytest
from test_memory_client import StateHandler, _make_client, _make_settings

from local.memory_client import AuthFailure, SecondBrainUnavailable


class TestDocumentMethods:
    def test_upload_success_parses_response(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        state = StateHandler()

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/documents/upload":
                state.requests.append(request)
                return httpx.Response(
                    201,
                    json={"document": {"id": "d-1", "filename": "brief.md",
                                       "mime_type": "text/markdown", "metadata": {"pages": 1}},
                          "chunks_indexed": 4},
                )
            return state.handle(request)

        monkeypatch.setattr(state, "handle", handle)
        client = _make_client(state, tmp_path)

        target = tmp_path / "brief.md"
        target.write_bytes(b"# hello\n\ndoc body")
        result = client.upload_document(str(target))
        assert result["chunks_indexed"] == 4
        sent = state.requests[-1]
        assert "multipart/form-data" in sent.headers.get("content-type", "")

    def test_upload_offline_raises_unavailable(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        state.mode = "down"
        client = _make_client(state, tmp_path)
        target = tmp_path / "a.txt"
        target.write_bytes(b"x")
        with pytest.raises(SecondBrainUnavailable):
            client.upload_document(str(target))

    def test_missing_file_raises(self, tmp_path):  # type: ignore[no-untyped-def]
        client = _make_client(StateHandler(), tmp_path)
        with pytest.raises(FileNotFoundError):
            client.upload_document(str(tmp_path / "ghost.md"))

    def test_list_documents_passthrough(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        state = StateHandler()

        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/v1/documents":
                return httpx.Response(
                    200,
                    json=[{"id": "d-1", "filename": "a.pdf", "mime_type": "application/pdf"}],
                )
            return state.handle(request)

        monkeypatch.setattr(state, "handle", handle)
        client = _make_client(state, tmp_path)
        docs = client.list_documents()
        assert docs and docs[0]["filename"] == "a.pdf"

    def test_delete_document_statuses(self, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
        state = StateHandler()

        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "DELETE" and request.url.path.startswith("/v1/documents/"):
                if request.url.path.endswith("gone"):
                    return httpx.Response(404, json={"error": {"code": "not_found", "message": "nf"}})
                return httpx.Response(204)
            return state.handle(request)

        monkeypatch.setattr(state, "handle", handle)
        client = _make_client(state, tmp_path)
        assert client.delete_document("d-1") is True
        assert client.delete_document("gone") is False

    def test_auth_failure_propagates(self, tmp_path):  # type: ignore[no-untyped-def]
        state = StateHandler()
        client = _make_client(state, tmp_path, settings=_make_settings(second_brain_api_key="wrong"))
        target = tmp_path / "b.md"
        target.write_bytes(b"data")
        with pytest.raises(AuthFailure):
            client.upload_document(str(target))
