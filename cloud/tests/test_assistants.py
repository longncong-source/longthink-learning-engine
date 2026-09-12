"""Assistant provisioning (1 tro ly ao / nhan vien): closed-mode CRUD + hot-reload."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cloud.tests.conftest import configure_test_env  # noqa: E402

ADMIN_KEY = "adm-key-001"
NV_KEY = "nv-key-001"

ACL = [
    {"key": ADMIN_KEY, "user": "admin_it", "phong": "admin", "role": "admin"},
    {"key": NV_KEY, "user": "tckt_nhanvien", "phong": "phong_tckt_chung",
     "role": "nhan_vien"},
]


@pytest.fixture()
def provision_client(monkeypatch, tmp_path):
    """Closed-mode app with FILE-backed settings in an isolated CWD.

    The tmp cloud/.env is the single source of truth, so provisioning
    exercises the real persist + hot-reload path (never the repo .env).
    """
    from fastapi.testclient import TestClient

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import reset_repository
    from cloud.app.embeddings import reset_embedding_provider
    from cloud.app.security import reset_limiters

    configure_test_env(monkeypatch, tmp_path)
    for var in ("MEMORY_API_KEYS", "ORG_ACL_JSON", "SQLITE_PATH"):
        monkeypatch.delenv(var, raising=False)
    envdir = tmp_path / "srv"
    (envdir / "cloud").mkdir(parents=True)
    env_file = envdir / "cloud" / ".env"
    env_file.write_text(
        "MEMORY_DB_BACKEND=sqlite\n"
        f"SQLITE_PATH={tmp_path / 'prov.sqlite3'}\n"
        f"MEMORY_API_KEYS={ADMIN_KEY},{NV_KEY}\n"
        f"ORG_ACL_JSON={json.dumps(ACL)}\n"
        "EMBEDDING_PROVIDER=hash\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(envdir)

    import cloud.app.services.assistant_service as svc

    monkeypatch.setattr(svc, "default_env_path", lambda: env_file)

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()
    reset_limiters()

    import importlib

    importlib.reload(main_module)
    app = main_module.create_app()
    with TestClient(app) as http:
        yield http, env_file

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()


def _h(key: str) -> dict:
    return {"X-Api-Key": key}


# ── pure service tests ──

def test_write_env_kv_replaces_all_dups_and_appends(tmp_path):
    from cloud.app.services.assistant_service import write_env_kv

    f = tmp_path / ".env"
    f.write_text("A=1\nMEMORY_API_KEYS=old\nB=2\nMEMORY_API_KEYS=old\n", encoding="utf-8")
    write_env_kv(f, {"MEMORY_API_KEYS": "new1,new2", "ORG_ACL_JSON": "[1]"})
    text = f.read_text(encoding="utf-8")
    assert text.count("MEMORY_API_KEYS=") == 1
    assert "MEMORY_API_KEYS=new1,new2" in text
    assert text.rstrip().endswith('ORG_ACL_JSON=[1]')
    assert "A=1" in text and "B=2" in text


def test_write_env_kv_missing_file(tmp_path):
    from cloud.app.services.assistant_service import ProvisioningError, write_env_kv

    with pytest.raises(ProvisioningError):
        write_env_kv(tmp_path / "nope.env", {"K": "v"})


def test_normalize_rejects_bad_input():
    from cloud.app.services.assistant_service import ProvisioningError, _normalize

    assert _normalize("Nguyen Van A", "phong_tckt_chung", "nhan_vien") == (
        "nguyen_van_a", "phong_tckt_chung", "nhan_vien")
    # bgd/admin phong auto-normalized.
    assert _normalize("Sep", "whatever", "bgd")[1] == "bgd"
    with pytest.raises(ProvisioningError):
        _normalize("A", "phong_tckt_chung", "sep")  # bad role
    with pytest.raises(ProvisioningError):
        # staff cannot sit directly in congty_chung
        _normalize("A", "congty_chung", "nhan_vien")
    with pytest.raises(ProvisioningError):
        _normalize("   ", "phong_tckt_chung", "nhan_vien")  # empty user


def test_describe_entry_never_exposes_key():
    from cloud.app.services.assistant_service import describe_entry

    view = describe_entry({"key": "lt-secret", "user": "u", "phong": "phong_tckt_chung",
                           "role": "nhan_vien"})
    assert "key" not in view and "api_key" not in view
    assert len(view["key_hint"]) == 8
    assert "phong_tckt_chung" in view["projects_allowed"]
    assert "memory.delete" not in view["tools_allowed"]


# ── HTTP tests (closed mode) ──

def test_list_masks_keys(provision_client):
    http, _ = provision_client
    r = http.get("/v1/admin/assistants", headers=_h(ADMIN_KEY))
    assert r.status_code == 200, r.text
    items = r.json()["assistants"]
    assert {a["user"] for a in items} == {"admin_it", "tckt_nhanvien"}
    assert all("key" not in a and "api_key" not in a for a in items)


def test_provision_gated(provision_client):
    http, _ = provision_client
    body = {"user": "new guy", "phong": "phong_tckt_chung", "role": "nhan_vien"}
    assert http.post("/v1/admin/assistants", json=body, headers=_h(NV_KEY)).status_code == 403
    assert http.post("/v1/admin/assistants", json=body).status_code in (401, 403)


def test_create_revoke_roundtrip(provision_client):
    http, env_file = provision_client
    adm = _h(ADMIN_KEY)
    # Create: key returned ONCE + personal project auto-created.
    r = http.post("/v1/admin/assistants",
                  json={"user": "Le Van B", "phong": "phong_tckt_chung",
                        "role": "nhan_vien", "data_policy": "local_only",
                        "rate_limit": 60},
                  headers=adm)
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["user"] == "le_van_b"
    assert created["api_key"].startswith("lt-")
    assert created["project_id"]
    # Persisted to the env file (both keys present).
    persisted = env_file.read_text(encoding="utf-8")
    assert created["api_key"] in persisted
    assert "le_van_b" in persisted
    # List shows the assistant, key masked.
    users = {a["user"] for a in http.get("/v1/admin/assistants", headers=adm).json()["assistants"]}
    assert "le_van_b" in users
    # Duplicate user -> 409.
    r = http.post("/v1/admin/assistants",
                  json={"user": "le van b", "phong": "phong_tckt_chung",
                        "role": "nhan_vien"},
                  headers=adm)
    assert r.status_code == 409
    # New key authenticates (in-process settings reloaded by provision path).
    from cloud.app.config import get_settings

    get_settings.cache_clear()
    assert created["api_key"] in get_settings().api_key_list
    # Revoke: key gone from file, user gone from list.
    r = http.delete("/v1/admin/assistants/le_van_b", headers=adm)
    assert r.status_code == 200 and r.json()["revoked"] is True
    assert created["api_key"] not in env_file.read_text(encoding="utf-8")
    assert http.delete("/v1/admin/assistants/le_van_b", headers=adm).status_code == 422


def test_hot_reload_new_key_usable_without_restart(monkeypatch, tmp_path):
    """End-to-end: file-backed settings + provision -> new key works immediately."""
    from fastapi.testclient import TestClient

    from cloud.app import main as main_module
    from cloud.app.config import get_settings
    from cloud.app.db import reset_repository
    from cloud.app.embeddings import reset_embedding_provider
    from cloud.app.security import reset_limiters

    for var in ("MEMORY_API_KEYS", "ORG_ACL_JSON", "SQLITE_PATH"):
        monkeypatch.delenv(var, raising=False)
    envdir = tmp_path / "srv"
    (envdir / "cloud").mkdir(parents=True)
    env_file = envdir / "cloud" / ".env"
    sqlite = tmp_path / "hot.sqlite3"
    env_file.write_text(
        "MEMORY_DB_BACKEND=sqlite\n"
        f"SQLITE_PATH={sqlite}\n"
        f"MEMORY_API_KEYS={ADMIN_KEY}\n"
        f"ORG_ACL_JSON={json.dumps(ACL)}\n"
        "EMBEDDING_PROVIDER=hash\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(envdir)
    import cloud.app.services.assistant_service as svc

    monkeypatch.setattr(svc, "default_env_path", lambda: env_file)

    get_settings.cache_clear()
    reset_repository()
    reset_embedding_provider()
    reset_limiters()

    import importlib

    importlib.reload(main_module)
    app = main_module.create_app()
    try:
        with TestClient(app) as http:
            adm = _h(ADMIN_KEY)
            r = http.post("/v1/admin/assistants",
                          json={"user": "hot reload", "phong": "phong_tckt_chung",
                                "role": "nhan_vien"},
                          headers=adm)
            assert r.status_code == 201, r.text
            new_key = r.json()["api_key"]
            # No restart: the fresh key authenticates and sees its own scope.
            r = http.get("/v1/projects", headers=_h(new_key))
            assert r.status_code == 200, r.text
            names = {p["name"] for p in r.json()}
            assert "nv_hot_reload" in names
            assert "bgd_rieng" not in names
    finally:
        get_settings.cache_clear()
        reset_repository()
        reset_embedding_provider()
