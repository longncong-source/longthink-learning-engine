"""CLI tests: parser structure + command handlers against a stubbed client."""

from __future__ import annotations

import json

import pytest

from local.brain_cli import build_parser, main


class StubStore:
    def pending_count(self) -> int:
        return 0


class StubClient:
    def __init__(self) -> None:
        self.store = StubStore()
        self.last_write: dict | None = None

    def health(self):
        return {"status": "ok"}

    def details(self):
        return 200, {
            "status": "ok",
            "storage": {"backend": "sqlite", "reachable": True, "counts": {"memories": 3}},
            "embeddings": {"provider": "hash", "model": "m", "dimension": 64},
        }

    def search(self, query, **kwargs):
        return {
            "query": query,
            "total": 1,
            "results": [{
                "id": "m-1", "type": "lesson", "title": "Review first",
                "content": "Review drawings before procurement.", "score": 0.9,
                "scores": {"semantic": 0.9, "keyword": 0.5, "importance": 0.7, "recency": 1.0},
                "metadata": {},
            }],
        }

    def write_memory(self, **kwargs):
        self.last_write = kwargs
        from local.memory_client import WriteOutcome

        return WriteOutcome(status="stored", memory_id="new-1")

    def list_memories(self, limit=20, project_id=None, mtype=None):
        return [{"id": "m-1", "type": "lesson", "title": "T", "importance": 0.7}]

    def delete_memory(self, memory_id):
        return memory_id == "known-id"

    def projects(self):
        return [{"id": "p-1", "name": "LNG Project", "status": "active"}]

    def ensure_project(self, name, description=""):
        return "p-1"

    def sync(self, max_items=None):
        from local.memory_client import SyncReport

        return SyncReport(sent=2, remaining=0)

    def upload_document(self, path, **kwargs):
        return {"document": {"id": "d-9", "filename": "brief.md", "mime_type": "text/markdown",
                             "metadata": {"pages": 1}},
                "chunks_indexed": 3}

    def list_documents(self, limit=50, project_id=None):
        return [{"id": "d-9", "filename": "brief.md", "mime_type": "text/markdown"}]

    def delete_document(self, document_id):
        return document_id == "d-9"


class TestDocCommands:
    def test_doc_upload_reports_chunks(self, patched_client, capsys, tmp_path):  # type: ignore[no-untyped-def]
        target = tmp_path / "brief.md"
        target.write_bytes(b"# content")
        exit_code = main(["doc", "upload", str(target)])
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "indexed: 3 chunk(s)" in captured
        assert "brief.md" in captured

    def test_doc_list(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        assert main(["doc", "list"]) == 0
        assert "brief.md" in capsys.readouterr().out

    def test_doc_delete_missing_is_error(self, patched_client):  # type: ignore[no-untyped-def]
        assert main(["doc", "delete", "nope"]) == 1


@pytest.fixture()
def patched_client(monkeypatch):  # type: ignore[no-untyped-def]
    stub = StubClient()
    monkeypatch.setattr("local.brain_cli._client", lambda settings=None: stub)
    return stub


class TestParserStructure:
    def test_all_spec_commands_exist(self):  # type: ignore[no-untyped-def]
        parser = build_parser()
        # spec section 28 surface
        for argv in (
            ["status"], ["doctor", "--json"],
            ["memory", "search", "mechanical delay"],
            ["memory", "add", "--title", "t", "--content", "c"],
            ["memory", "list"],
            ["project", "list"],
            ["project", "create", "X"],
            ["sync"],
            ["demo", "--yes"],
        ):
            args = parser.parse_args(argv)
            assert hasattr(args, "func")


class TestHandlers:
    def test_memory_search_json_output(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        exit_code = main(["memory", "search", "delay", "--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert exit_code == 0
        assert data["total"] == 1
        assert data["results"][0]["id"] == "m-1"

    def test_memory_add_passes_flags(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        exit_code = main([
            "memory", "add",
            "--title", "Decision A",
            "--content", "We decided to require drawings early",
            "--type", "decision", "--importance", "0.85",
        ])
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "stored" in captured
        assert patched_client.last_write["type"] == "decision"
        assert patched_client.last_write["importance"] == pytest.approx(0.85)

    def test_sync_report(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        exit_code = main(["sync"])
        captured = capsys.readouterr().out
        assert exit_code == 0
        assert "sent=2" in captured

    def test_delete_missing_returns_error_code(self, patched_client):  # type: ignore[no-untyped-def]
        assert main(["memory", "delete", "missing-id"]) == 1

    def test_status_ok(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        exit_code = main(["status"])
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "Second Brain" in out

    def test_doctor_reports_sections(self, patched_client, capsys):  # type: ignore[no-untyped-def]
        exit_code = main(["doctor", "--quick"])
        out = capsys.readouterr().out
        assert "First Brain" in out and "Second Brain" in out
        # With stubbed API up + key accepted, doctor should pass its critical checks.
        assert exit_code == 0
