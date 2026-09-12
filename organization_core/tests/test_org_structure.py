"""Phase 03 tests: DAK seed, org tree, history, project matrix, APIs."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import org_structure
from organization_core.api import create_org_app
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import DEPARTMENTS, seed_dak
from organization_core.store import OrganizationStore

PAST = "2000-01-01T00:00:00+00:00"
MID = "2010-06-01T00:00:00+00:00"
PAST_END = "2020-01-01T00:00:00+00:00"
FUTURE = "2100-01-01T00:00:00+00:00"

EXPECTED_DEPTS = {"BGD"} | {c for c, _ in DEPARTMENTS}


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase03.sqlite3"))
    seed_dak(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    return TestClient(create_org_app(store))


def _dept_id(store, code):
    row = store.query_one("SELECT id FROM departments WHERE code = ?", (code,))
    assert row is not None
    return row["id"]


def _person(store, code):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    return pid


def _seat(store, person_id, position_code):
    row = store.query_one(
        "SELECT id FROM positions WHERE code = ?", (position_code,))
    assert row is not None, position_code
    now = utcnow_iso()
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), person_id, row["id"], now, now),
    )


def _project(store, code):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    return pid


def _project_role(store, code):
    rid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO project_roles (id, code, name, authority_level,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 1, ?, ?, 0)",
        (rid, code, code, now, now),
    )
    return rid


def test_dak_seed_extended(store):
    codes = {r["code"] for r in store.query_all("SELECT code FROM departments")}
    assert codes >= EXPECTED_DEPTS
    pos_codes = {r["code"] for r in
                 store.query_all("SELECT code FROM positions")}
    assert "DAK-BGD-GD" in pos_codes and "DAK-BGD-PGD" in pos_codes
    for dept, _ in DEPARTMENTS:
        for suffix in ("TP", "PP", "CV", "KSC", "KS", "CS", "NV"):
            assert f"DAK-{dept}-{suffix}" in pos_codes, f"DAK-{dept}-{suffix}"
    assert "DAK-TCKT-TQ" in pos_codes
    assert store.count("persons", "is_deleted = 0") == 0
    version = org_structure.current_version(store)
    assert version is not None and version["version"] == "v2026.01"


def test_organization_tree_api(client):
    resp = client.get("/v1/organization")
    assert resp.status_code == 200
    body = resp.json()
    assert body["company"]["code"] == "DAK"
    assert body["version"]["version"] == "v2026.01"
    codes = {d["code"] for d in body["departments"]}
    assert codes >= EXPECTED_DEPTS
    tchc = next(d for d in body["departments"] if d["code"] == "TCHC")
    assert tchc["position_count"] >= 7


def test_departments_endpoints(client, store):
    resp = client.get("/v1/departments")
    assert resp.status_code == 200
    assert len(resp.json()["departments"]) == 8
    did = _dept_id(store, "KTGS")
    resp = client.get(f"/v1/departments/{did}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "KTGS"
    assert len(body["positions"]) >= 7
    assert client.get("/v1/departments/no-such-id").status_code == 404


def test_historical_structure(store, client):
    now = utcnow_iso()
    company = store.query_one("SELECT id FROM companies WHERE code = 'DAK'")
    hid = new_id()
    store.execute(
        "INSERT INTO departments (id, company_id, code, name, dept_type,"
        " status, effective_from, effective_to, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, 'HIST', 'Historic Dept', 'functional',"
        " 'inactive', ?, ?, ?, ?, 0)",
        (hid, company["id"], PAST, PAST_END, now, now),
    )
    current = client.get("/v1/organization")
    assert "HIST" not in {d["code"] for d in current.json()["departments"]}
    historic = client.get("/v1/organization", params={"at": MID})
    assert "HIST" in {d["code"] for d in historic.json()["departments"]}
    assert client.get("/v1/departments", params={"at": MID}).status_code == 200
    hist_list = client.get("/v1/departments", params={"at": MID}).json()
    assert "HIST" in {d["code"] for d in hist_list["departments"]}


def test_future_version_not_current(store):
    now = utcnow_iso()
    store.execute(
        "INSERT INTO org_versions (id, version, label, status, effective_from,"
        " effective_to, detail, created_at, updated_at, is_deleted)"
        " VALUES (?, 'v9999.99', 'future', 'active', ?, NULL, '{}', ?, ?, 0)",
        (new_id(), FUTURE, now, now),
    )
    assert org_structure.current_version(store)["version"] == "v2026.01"
    assert len(org_structure.list_versions(store)) == 2


def test_multiple_project_assignments(client, store):
    pid = _person(store, "matrix-person")
    _seat(store, pid, "DAK-PTDA-TP")
    p1, p2 = _project(store, "PX1"), _project(store, "PX2")
    dev, lead = _project_role(store, "DEV"), _project_role(store, "LEAD")
    now = utcnow_iso()
    for proj, role in ((p1, dev), (p2, lead)):
        store.execute(
            "INSERT INTO project_assignments (id, project_id, person_id,"
            " project_role_id, status, created_at, updated_at, is_deleted)"
            " VALUES (?, ?, ?, ?, 'active', ?, ?, 0)",
            (new_id(), proj, pid, role, now, now),
        )
    resp = client.get(f"/v1/people/{pid}/projects")
    assert resp.status_code == 200
    projects = resp.json()["projects"]
    assert {p["project_code"] for p in projects} == {"PX1", "PX2"}
    roles = {p["project_code"]: p["project_role_code"] for p in projects}
    assert roles == {"PX1": "DEV", "PX2": "LEAD"}
    team1 = client.get(f"/v1/projects/{p1}/team").json()
    team2 = client.get(f"/v1/projects/{p2}/team").json()
    assert [m["person_code"] for m in team1["members"]] == ["matrix-person"]
    assert team1["members"][0]["project_role_code"] == "DEV"
    assert team2["members"][0]["project_role_code"] == "LEAD"
    assert team1["members"][0]["departments"][0]["code"] == "PTDA"


def test_person_context(client, store):
    pid = _person(store, "ctx-person")
    _seat(store, pid, "DAK-TCHC-CV")
    p1 = _project(store, "CTX1")
    now = utcnow_iso()
    store.execute(
        "INSERT INTO project_assignments (id, project_id, person_id, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (new_id(), p1, pid, now, now),
    )
    resp = client.get(f"/v1/people/{pid}/context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["person"]["code"] == "ctx-person"
    assert body["company"]["code"] == "DAK"
    assert [d["code"] for d in body["departments"]] == ["TCHC"]
    assert body["projects"][0]["project_code"] == "CTX1"
    assert body["version"]["version"] == "v2026.01"
    assert client.get("/v1/people/no-such-id/context").status_code == 404


def test_position_person_separation(client, store):
    pid = _person(store, "leaver")
    _seat(store, pid, "DAK-AT-NV")
    pos_before = store.count(
        "positions", "code = ? AND is_deleted = 0", ("DAK-AT-NV",))
    assert pos_before == 1
    store.execute("UPDATE persons SET is_deleted = 1 WHERE id = ?", (pid,))
    # position template survives; person is gone from API
    assert store.count(
        "positions", "code = ? AND is_deleted = 0", ("DAK-AT-NV",)) == 1
    assert client.get(f"/v1/people/{pid}").status_code == 404
    at_dept = _dept_id(store, "AT")
    body = client.get(f"/v1/departments/{at_dept}").json()
    assert "DAK-AT-NV" in {p["code"] for p in body["positions"]}


def test_health_and_404s(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/v1/people/no-such-id").status_code == 404
    assert client.get("/v1/projects/no-such-id/team").status_code == 404
