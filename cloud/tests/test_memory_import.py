"""Bulk memory import tests: json/jsonl/csv/md/txt -> many memories via one call."""

from __future__ import annotations

import json

from cloud.tests.conftest import AUTH_HEADERS


def _import(client, name: str, data: bytes, **form):  # type: ignore[no-untyped-def]
    return client.post(
        "/v1/memory/import",
        files={"file": (name, data, "application/octet-stream")},
        data=form or None,
        headers=AUTH_HEADERS,
    )


class TestMemoryImport:
    def test_requires_auth(self, client):  # type: ignore[no-untyped-def]
        resp = client.post(
            "/v1/memory/import",
            files={"file": ("a.json", b"[]", "application/octet-stream")},
        )
        assert resp.status_code == 401

    def test_unsupported_extension_415(self, client):  # type: ignore[no-untyped-def]
        resp = _import(client, "data.exe", b"MZ")
        assert resp.status_code == 415
        assert resp.json()["error"]["code"] == "unsupported_media_type"

    def test_json_array_import(self, client):  # type: ignore[no-untyped-def]
        payload = [
            {"title": "Quyết định A", "content": "Nội dung quyết định A", "type": "decision",
             "importance": 0.9},
            {"title": "Bài học B", "content": "Nội dung bài học B", "type": "lesson"},
        ]
        resp = _import(client, "items.json", json.dumps(payload).encode())
        assert resp.status_code == 201
        body = resp.json()
        assert body["format"] == "json"
        assert body["total_parsed"] == 2
        assert body["created"] == 2
        assert len(body["memory_ids"]) == 2

        listed = client.get("/v1/memory", params={"limit": 50}, headers=AUTH_HEADERS).json()
        imported = [m for m in listed if m["source"] and m["source"].startswith("file-import:")]
        assert {m["title"] for m in imported} >= {"Quyết định A", "Bài học B"}

    def test_json_items_wrapper(self, client):  # type: ignore[no-untyped-def]
        payload = {"items": [{"title": "wrapped", "content": "wrapper format works"}]}
        body = _import(client, "w.json", json.dumps(payload).encode()).json()
        assert body["created"] == 1

    def test_jsonl_import_skips_blank_lines(self, client):  # type: ignore[no-untyped-def]
        lines = '\n{"title":"one","content":"first"}\n\n{"title":"two","content":"second"}\n'
        body = _import(client, "l.jsonl", lines.encode()).json()
        assert body["format"] == "jsonl"
        assert body["created"] == 2

    def test_malformed_json_422(self, client):  # type: ignore[no-untyped-def]
        resp = _import(client, "bad.json", b"{not valid")
        assert resp.status_code == 422

    def test_csv_import_with_optional_columns(self, client):  # type: ignore[no-untyped-def]
        csv_data = (
            "title,content,type,importance\n"
            "Hạng mục 1,Nội dung một,task,0.7\n"
            "Hạng mục 2,Nội dung hai,,\n"
        )
        body = _import(client, "rows.csv", csv_data.encode()).json()
        assert body["format"] == "csv"
        assert body["created"] == 2

    def test_csv_missing_required_columns_422(self, client):  # type: ignore[no-untyped-def]
        resp = _import(client, "bad.csv", b"only_one_column\nvalue\n")
        assert resp.status_code == 422

    def test_markdown_heading_split(self, client):  # type: ignore[no-untyped-def]
        md = "# Quy tắc dự án\nNội dung quy tắc.\n\n## Bài học trích xuất\nKhông bỏ qua review.\n"
        body = _import(client, "notes.md", md.encode()).json()
        assert body["format"] == "markdown"
        assert body["created"] == 2

    def test_plaintext_paragraph_split(self, client):  # type: ignore[no-untyped-def]
        txt = "Đoạn đầu tiên có nội dung.\n\nĐoạn thứ hai cũng vậy.\n\nĐoạn thứ ba kết thúc."
        body = _import(client, "notes.txt", txt.encode()).json()
        assert body["format"] == "text"
        assert body["created"] == 3

    def test_item_error_isolated(self, client):  # type: ignore[no-untyped-def]
        payload = [
            {"title": "ok item", "content": "fine"},
            {"title": "broken item"},  # missing content
        ]
        body = _import(client, "mixed.json", json.dumps(payload).encode()).json()
        assert body["created"] == 1
        assert len(body["errors"]) == 1
        assert body["errors"][0]["index"] == 1

    def test_unknown_project_404(self, client):  # type: ignore[no-untyped-def]
        import uuid

        resp = _import(client, "x.json", b"[]", project_id=str(uuid.uuid4()))
        assert resp.status_code == 404

    def test_default_type_applied(self, client):  # type: ignore[no-untyped-def]
        body = _import(client, "t.json", b'[{"title":"t","content":"c"}]',
                       default_type="lesson").json()
        assert body["created"] == 1
        listed = client.get("/v1/memory", params={"type": "lesson", "limit": 20},
                            headers=AUTH_HEADERS).json()
        assert any(m["title"] == "t" for m in listed)

    def test_metrics_and_audit_recorded(self, client):  # type: ignore[no-untyped-def]
        _import(client, "a.json", b'[{"title":"metric probe","content":"counted"}]')
        metrics_text = client.get("/v1/admin/metrics", headers=AUTH_HEADERS).text
        assert "fsb_memory_imports_total" in metrics_text
        events = client.get("/v1/admin/audit?limit=100", headers=AUTH_HEADERS).json()["events"]
        assert any(e.get("kind") == "memory.import" for e in events)

    def test_imported_memories_appear_in_graph(self, client):  # type: ignore[no-untyped-def]
        project = client.post("/v1/projects", json={"name": "Bulk Proj"}, headers=AUTH_HEADERS).json()
        _import(client, "g.json",
                json.dumps([{"title": "graph bulk", "content": "bulk node"}]).encode(),
                project_id=project["id"])
        graph = client.get("/v1/graph", headers=AUTH_HEADERS).json()
        titles = {n["label"] for n in graph["nodes"]}
        assert "graph bulk" in titles
        links = [lnk for lnk in graph["links"]
                 if lnk["kind"] == "belongs_to" and lnk["target"] == f"p:{project['id']}"]
        assert links, "imported memory must link to the project node"
