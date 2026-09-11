"""Multi-assistant ACL (6 phong + BGD): closed-mode enforcement + new mid-brain endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.tests.conftest import TEST_API_KEY  # noqa: E402

NV_KEY = TEST_API_KEY  # nhan_vien TCKT
BGD_KEY = "bgd-key-abc"
ADMIN_KEY = "admin-key-xyz"
UNKNOWN_KEY = "other-key-999"
TP_KEY = "tp-key-tckt"
RL_KEY = "rl-key-tckt"

ACL = [
    {"key": NV_KEY, "user": "tckt_nhanvien", "phong": "phong_tckt_chung",
     "role": "nhan_vien", "data_policy": "local_only"},
    {"key": TP_KEY, "user": "tckt_truongphong", "phong": "phong_tckt_chung",
     "role": "truong_phong", "data_policy": "local_only",
     "reports": ["tckt_nhanvien"]},
    {"key": RL_KEY, "user": "tckt_quota", "phong": "phong_tckt_chung",
     "role": "nhan_vien", "data_policy": "local_only", "rate_limit": 3},
    {"key": BGD_KEY, "user": "bgd_giamdoc", "phong": "bgd",
     "role": "bgd", "data_policy": "cloud_allowed"},
    {"key": ADMIN_KEY, "user": "admin_it", "phong": "admin",
     "role": "admin", "data_policy": "local_only"},
]


@pytest.fixture()
def acl_client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import reset_repository
    from cloud.app.embeddings import reset_embedding_provider
    from cloud.tests.conftest import configure_test_env

    configure_test_env(
        monkeypatch, tmp_path,
        MEMORY_API_KEYS=",".join([NV_KEY, TP_KEY, RL_KEY, BGD_KEY, ADMIN_KEY, UNKNOWN_KEY]),
        ORG_ACL_JSON=json.dumps(ACL),
    )
    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()
    from cloud.app.security import reset_limiters

    reset_limiters()

    import importlib

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as http:
        yield http

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()


def _headers(key: str) -> dict:
    return {"X-Api-Key": key}


@pytest.fixture()
def projects(acl_client):
    from cloud.app.db import ProjectRecord, get_repository

    repo = get_repository()
    ids = {}
    for name in ("congty_chung", "phong_tckt_chung", "phong_tkcn_chung"):
        rec = repo.find_project_by_name(name) or repo.create_project(ProjectRecord(name=name))
        ids[name] = str(rec.id)
    return ids


def test_unknown_key_denied_in_closed_mode(acl_client):
    r = acl_client.get("/v1/memory", headers=_headers(UNKNOWN_KEY))
    assert r.status_code == 403


def test_write_requires_project_scope(acl_client, projects):
    # Unscoped write as nhan_vien -> 403 (BGD-only).
    r = acl_client.post("/v1/memory",
                        json={"title": "t", "content": "unscoped content here"},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # Allowed project -> 201 with actor stamp.
    r = acl_client.post("/v1/memory",
                        json={"title": "tckt note", "content": "quyet toan q3 xong",
                              "project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 201, r.text
    assert r.json()["memory"]["metadata"]["_actor"] == "tckt_nhanvien"
    # Foreign phong -> 403.
    r = acl_client.post("/v1/memory",
                        json={"title": "x", "content": "tkcn secret stuff",
                              "project_id": projects["phong_tkcn_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403


def test_search_post_filters_to_allowed_scope(acl_client, projects):
    bgd_h = _headers(BGD_KEY)
    acl_client.post("/v1/memory",
                    json={"title": "chung", "content": "thong bao nghi le chung",
                          "project_id": projects["congty_chung"]}, headers=bgd_h)
    acl_client.post("/v1/memory",
                    json={"title": "tkcn", "content": "ban ve thiet ke lo hoi",
                          "project_id": projects["phong_tkcn_chung"]}, headers=bgd_h)
    r = acl_client.post("/v1/memory/search", json={"query": "thong bao ban ve", "top_k": 10},
                        headers=_headers(NV_KEY))
    assert r.status_code == 200
    titles = {item["title"] for item in r.json()["results"]}
    assert "tkcn" not in titles


def test_delete_is_bgd_only(acl_client, projects):
    r = acl_client.post("/v1/memory",
                        json={"title": "del me", "content": "tam xoa sau",
                              "project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    mid = r.json()["memory"]["id"]
    assert acl_client.delete(f"/v1/memory/{mid}", headers=_headers(NV_KEY)).status_code == 403
    assert acl_client.delete(f"/v1/memory/{mid}", headers=_headers(BGD_KEY)).status_code == 204


def test_admin_cannot_read_memory_but_can_audit(acl_client):
    assert acl_client.post("/v1/memory/search", json={"query": "x"},
                           headers=_headers(ADMIN_KEY)).status_code == 403
    r = acl_client.get("/v1/admin/audit", headers=_headers(ADMIN_KEY))
    assert r.status_code == 200
    assert "events" in r.json()


def test_midbrain_process_requires_scope(acl_client, projects):
    # No project_id as nhan_vien -> 403.
    r = acl_client.post("/v1/mid-brain/process", json={"question": "quyet toan?"},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # Scoped -> 200.
    r = acl_client.post("/v1/mid-brain/process",
                        json={"question": "quyet toan q3?", "project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 200, r.text
    assert "answer" in r.json()


def test_plan_execute_trace_approvals(acl_client, projects):
    nv_h, bgd_h = _headers(NV_KEY), _headers(BGD_KEY)
    # nhan_vien lacks plan.execute -> 403 on execute/approvals.
    r = acl_client.post("/v1/mid-brain/plan",
                        json={"goal": "research quyet toan",
                              "project_id": projects["phong_tckt_chung"]}, headers=nv_h)
    assert r.status_code == 200, r.text
    plan_id = r.json()["plan_id"]
    assert acl_client.post("/v1/mid-brain/execute", json={"plan_id": plan_id},
                           headers=nv_h).status_code == 403
    assert acl_client.get("/v1/mid-brain/approvals/pending",
                          headers=nv_h).status_code == 403
    # BGD executes (medium-risk research tasks run; adapter fails soft without CLI).
    r = acl_client.post("/v1/mid-brain/execute", json={"plan_id": plan_id}, headers=bgd_h)
    assert r.status_code == 200, r.text
    assert r.json()["plan_id"] == plan_id
    assert isinstance(r.json()["results"], list)
    # Unknown trace -> 404; pending list visible to BGD.
    assert acl_client.get("/v1/mid-brain/trace/does-not-exist",
                          headers=bgd_h).status_code == 404
    r = acl_client.get("/v1/mid-brain/approvals/pending", headers=bgd_h)
    assert r.status_code == 200 and "pending" in r.json()


def test_truong_phong_reports_readonly(acl_client):
    from cloud.app.db import ProjectRecord, get_repository

    repo = get_repository()
    rec = repo.find_project_by_name("nv_tckt_nhanvien") or repo.create_project(
        ProjectRecord(name="nv_tckt_nhanvien"))
    personal_id = str(rec.id)
    nv_h, tp_h = _headers(NV_KEY), _headers(TP_KEY)
    # NV writes into own personal project.
    r = acl_client.post("/v1/memory",
                        json={"title": "ca nhan", "content": "ghi chep ca nhan cua toi",
                              "project_id": personal_id}, headers=nv_h)
    assert r.status_code == 201, r.text
    mid = r.json()["memory"]["id"]
    # TP reads report's personal memory but cannot write into it.
    assert acl_client.get(f"/v1/memory/{mid}", headers=tp_h).status_code == 200
    r = acl_client.post("/v1/memory",
                        json={"title": "sua ho", "content": "truong phong chen vao",
                              "project_id": personal_id}, headers=tp_h)
    assert r.status_code == 403


def test_rate_limit_per_key(acl_client):
    rl_h = _headers(RL_KEY)
    codes = [acl_client.get("/v1/projects", headers=rl_h).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:], codes


def test_watch_manage_restricted(acl_client):
    assert acl_client.post("/v1/documents/watch/scan",
                           headers=_headers(NV_KEY)).status_code == 403
    assert acl_client.post("/v1/documents/watch/scan",
                           headers=_headers(BGD_KEY)).status_code == 200
    assert acl_client.post("/v1/documents/watch/scan",
                           headers=_headers(ADMIN_KEY)).status_code == 200


def test_identity_defaults_and_admin_policy():
    from cloud.app.identity import Identity, _default_projects, _default_tools
    nv_projects = _default_projects("Nguyen Van A", "phong_tckt_chung", "nhan_vien")
    assert nv_projects == ("congty_chung", "phong_tckt_chung", "nv_nguyen_van_a")
    assert "memory.delete" not in _default_tools("phong_tckt_chung", "nhan_vien")
    assert "code.execute" in _default_tools("phong_tkcn_chung", "nhan_vien")
    assert "code.execute" not in _default_tools("phong_tckt_chung", "nhan_vien")
    assert _default_tools("bgd", "bgd") == ("*",)

    admin = Identity(user="admin_it", phong="admin", role="admin",
                     projects_allowed=(), tools_allowed=("project.list",))
    assert admin.effective_data_policy == "local_only"
    bgd = Identity(user="bgd", phong="bgd", role="bgd",
                   projects_allowed=("*",), tools_allowed=("*",), data_policy="cloud_allowed")
    assert bgd.effective_data_policy == "cloud_allowed"


# ── P0 hardening: bypass routes closed in the security review ──

def test_proxy_requires_auth(acl_client):
    # No key at all -> 401 (was: unauthenticated drive-by to :4096/:3001).
    assert acl_client.get("/code/").status_code == 401
    assert acl_client.get("/odc/").status_code == 401
    assert acl_client.get("/api/sessions").status_code == 401
    # Wrong key -> 401.
    assert acl_client.get("/code/", headers=_headers("nope")).status_code == 401
    # Valid key via header or ?api_key= passes auth (502 = OpenCode down, not 401).
    assert acl_client.get("/code/", headers=_headers(NV_KEY)).status_code != 401
    assert acl_client.get(f"/code/?api_key={NV_KEY}").status_code != 401


def test_code_config_hides_password(acl_client):
    r = acl_client.get("/v1/code/config", headers=_headers(NV_KEY))
    assert r.status_code == 200
    body = r.json()
    assert "password" not in body
    assert "configured" in body


def test_voice_ask_requires_scope_before_stt(acl_client, projects):
    files = {"audio": ("mic.webm", b"dummy-audio-bytes", "audio/webm")}
    # NV without project -> 403 from the scope gate (STT never runs).
    r = acl_client.post("/v1/voice/ask", files=files, headers=_headers(NV_KEY))
    assert r.status_code == 403
    # NV with a foreign project -> 403.
    r = acl_client.post("/v1/voice/ask", files=files,
                        data={"project_id": projects["phong_tkcn_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # NV with allowed project passes the gate (STT backend missing -> 5xx, not 403).
    r = acl_client.post("/v1/voice/ask", files=files,
                        data={"project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code != 403, r.text


def test_obsidian_sync_requires_scope(acl_client, projects):
    note = "---\nsync_to_brain: true\n---\nGhi chep hop giao ban phong"
    # NV without project -> 403.
    r = acl_client.post("/v1/obsidian/sync",
                        json={"file": "hop.md", "content": note},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # NV into allowed project -> 201 indexed.
    r = acl_client.post("/v1/obsidian/sync",
                        json={"file": "hop.md", "content": note,
                              "project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "indexed"
    # NV into foreign project -> 403.
    r = acl_client.post("/v1/obsidian/sync",
                        json={"file": "hop.md", "content": note,
                              "project_id": projects["phong_tkcn_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # vault-sync walks server paths -> watch.manage only (NV denied).
    r = acl_client.post("/v1/obsidian/vault-sync",
                        json={"vault_path": ".",
                              "project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403


def test_memory_import_requires_scope(acl_client, projects):
    import json as _json

    payload = _json.dumps([{"title": "imp", "content": "noi dung import thu nghiem"}])
    files = {"file": ("notes.json", payload.encode(), "application/json")}
    # NV without project -> 403.
    r = acl_client.post("/v1/memory/import", files=files, headers=_headers(NV_KEY))
    assert r.status_code == 403
    # NV into foreign project -> 403.
    r = acl_client.post("/v1/memory/import", files=files,
                        data={"project_id": projects["phong_tkcn_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 403
    # NV into allowed project -> 201.
    r = acl_client.post("/v1/memory/import", files=files,
                        data={"project_id": projects["phong_tckt_chung"]},
                        headers=_headers(NV_KEY))
    assert r.status_code == 201, r.text
    assert r.json()["created"] >= 1


def test_graph_post_filters_scope(acl_client, projects):
    bgd_h = _headers(BGD_KEY)
    acl_client.post("/v1/memory",
                    json={"title": "g-tckt", "content": "graph scope tckt proof",
                          "project_id": projects["phong_tckt_chung"]}, headers=bgd_h)
    acl_client.post("/v1/memory",
                    json={"title": "g-tkcn", "content": "graph scope tkcn proof",
                          "project_id": projects["phong_tkcn_chung"]}, headers=bgd_h)
    # Unscoped graph as NV: only allowed projects/memories leak through.
    r = acl_client.get("/v1/graph?max_memories=100", headers=_headers(NV_KEY))
    assert r.status_code == 200, r.text
    labels = {n.get("label") for n in r.json()["nodes"]}
    assert "phong_tkcn_chung" not in labels
    assert not any(isinstance(n.get("label"), str) and "g-tkcn" in n["label"]
                   for n in r.json()["nodes"])
    # Scoped to a foreign project -> 403.
    r = acl_client.get(f"/v1/graph?project_id={projects['phong_tkcn_chung']}",
                       headers=_headers(NV_KEY))
    assert r.status_code == 403
    # Scoped to own project -> 200.
    r = acl_client.get(f"/v1/graph?project_id={projects['phong_tckt_chung']}",
                       headers=_headers(NV_KEY))
    assert r.status_code == 200


def test_admin_endpoints_gated(acl_client):
    nv_h = _headers(NV_KEY)
    assert acl_client.get("/v1/admin/audit", headers=nv_h).status_code == 403
    assert acl_client.get("/v1/admin/metrics", headers=nv_h).status_code == 403
    assert acl_client.get("/v1/admin/metrics", headers=_headers(BGD_KEY)).status_code == 200


def test_lmstudio_switch_gated(acl_client, monkeypatch):
    assert acl_client.post("/v1/lmstudio/switch?provider=auto",
                           headers=_headers(NV_KEY)).status_code == 403

    class _FakeProc:
        stdout = "switched"
        returncode = 0

    import subprocess as _subprocess

    monkeypatch.setattr(_subprocess, "run", lambda *a, **k: _FakeProc())
    # BGD passes the gate (subprocess stubbed, no side effects).
    r = acl_client.post("/v1/lmstudio/switch?provider=auto", headers=_headers(BGD_KEY))
    assert r.status_code == 200, r.text


def test_stats_scope_checked(acl_client, projects):
    nv_h = _headers(NV_KEY)
    # Unscoped stats are BGD-only (even counts stay inside a scope).
    assert acl_client.get("/v1/mid-brain/knowledge/stats", headers=nv_h).status_code == 403
    # Own scope allowed; forged/foreign scope denied.
    assert acl_client.get(
        f"/v1/mid-brain/knowledge/stats?project_id={projects['phong_tckt_chung']}",
        headers=nv_h).status_code == 200
    assert acl_client.get("/v1/mid-brain/knowledge/stats?project_id=00000000-0000-0000-0000-000000000000",
                          headers=nv_h).status_code == 403
    assert acl_client.get(f"/v1/mid-brain/learning/stats?project_id={projects['phong_tkcn_chung']}",
                          headers=nv_h).status_code == 403


def test_execute_cross_scope_denied(acl_client, projects):
    tp_h, bgd_h = _headers(TP_KEY), _headers(BGD_KEY)
    # BGD builds a plan inside TKCN scope; TCKT truong_phong must not run it.
    r = acl_client.post("/v1/mid-brain/plan",
                        json={"goal": "research thiet ke lo hoi",
                              "project_id": projects["phong_tkcn_chung"]}, headers=bgd_h)
    assert r.status_code == 200, r.text
    plan_id = r.json()["plan_id"]
    assert acl_client.post("/v1/mid-brain/execute", json={"plan_id": plan_id},
                           headers=tp_h).status_code == 403
    # Same-scope execution stays allowed.
    r = acl_client.post("/v1/mid-brain/plan",
                        json={"goal": "research quyet toan",
                              "project_id": projects["phong_tckt_chung"]}, headers=tp_h)
    assert r.status_code == 200, r.text
    r = acl_client.post("/v1/mid-brain/execute",
                        json={"plan_id": r.json()["plan_id"]}, headers=tp_h)
    assert r.status_code == 200, r.text
