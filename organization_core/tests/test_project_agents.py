"""Phase 06 tests: project layer, roles, isolation, relations, dashboard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import project_agents as projs
from organization_core.api import create_org_app
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase06.sqlite3"))
    seed_dak(s)
    projs.ensure_project_roles(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    return TestClient(create_org_app(store))


def _person(store, code):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    pos = store.query_one(
        "SELECT id FROM positions WHERE code = 'DAK-TKCN-KS'")
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, pos["id"], now, now),
    )
    return pid


def test_project_creation_and_agent(store):
    project = projs.create_project(store, "DA001", "Du an A")
    assert project["code"] == "DA001"
    same = projs.create_project(store, "DA001", "Du an A")
    assert same["id"] == project["id"]
    agent = projs.ensure_project_agent(store, project["id"])
    assert agent["kind"] == "project"
    assert agent["config"]["final_approver"] is False
    assert "milestones" in agent["config"]["responsibilities"]
    with pytest.raises(LookupError):
        projs.ensure_project_agent(store, "missing")


def test_role_catalog_configurable(store):
    roles = projs.ensure_project_roles(store)
    codes = {r["code"] for r in roles}
    for expected in ("PROJECT_MANAGER", "PROJECT_ENGINEER", "DISCIPLINE_LEAD",
                     "DOCUMENT_CONTROLLER", "CONTRACT_SPECIALIST", "QA_QC",
                     "HSE", "FINANCE", "PLANNING"):
        assert expected in codes
    custom = projs.ensure_project_roles(
        store, extra=[("SAFETY_OFFICER", "Safety Officer", 45)])
    assert "SAFETY_OFFICER" in {r["code"] for r in custom}
    again = projs.ensure_project_roles(
        store, extra=[("SAFETY_OFFICER", "Safety Officer", 45)])
    assert len(again) == len(custom)
    assert store.count("project_roles", "code = 'SAFETY_OFFICER'") == 1


def test_assignment_and_role_scope(store):
    alice = _person(store, "alice06")
    bob = _person(store, "bob06")
    p1 = projs.create_project(store, "DA002", "Du an B")
    projs.assign_member(store, p1["id"], alice, "PROJECT_MANAGER")
    projs.assign_member(store, p1["id"], bob, "QA_QC")
    team = store.query_all(
        "SELECT * FROM project_assignments WHERE project_id = ?"
        " AND is_deleted = 0",
        (p1["id"],))
    assert len(team) == 2
    with pytest.raises(LookupError):
        projs.assign_member(store, p1["id"], alice, "NO_SUCH_ROLE")


def test_project_isolation(client, store):
    alice = _person(store, "alice06b")
    bob = _person(store, "bob06b")
    p1 = projs.create_project(store, "DA003", "Du an C")
    p2 = projs.create_project(store, "DA004", "Du an D")
    projs.assign_member(store, p1["id"], alice, "PROJECT_ENGINEER")
    projs.assign_member(store, p2["id"], bob, "PROJECT_ENGINEER")
    team1 = client.get(f"/v1/projects/{p1['id']}/team").json()["members"]
    team2 = client.get(f"/v1/projects/{p2['id']}/team").json()["members"]
    assert [m["person_code"] for m in team1] == ["alice06b"]
    assert [m["person_code"] for m in team2] == ["bob06b"]
    projs.add_task(store, p1["id"], "task p1", alice)
    tasks2 = client.get(f"/v1/projects/{p2['id']}/tasks").json()["tasks"]
    assert tasks2["total"] == 0


def test_relationships_and_dashboard(client, store):
    alice = _person(store, "alice06c")
    proj = projs.create_project(store, "DA005", "Du an E")
    projs.assign_member(store, proj["id"], alice, "DISCIPLINE_LEAD")
    projs.add_task(store, proj["id"], "thiet ke", alice)
    projs.add_milestone(store, proj["id"], "M1: xong thiet ke")
    projs.add_risk(store, proj["id"], "cham tien do vat lieu", "high")
    projs.add_issue(store, proj["id"], "thieu ban ve")
    projs.add_decision(store, proj["id"], "chon phuong an 2", "ly do...")
    pid = proj["id"]
    assert client.get(f"/v1/projects/{pid}/tasks").json()["tasks"]["total"] == 1
    assert len(client.get(f"/v1/projects/{pid}/milestones").json()
               ["milestones"]) == 1
    risks = client.get(f"/v1/projects/{pid}/risks").json()["risks"]
    assert risks["open"] == 1
    assert len(client.get(f"/v1/projects/{pid}/issues").json()
               ["issues"]["items"]) == 1
    assert len(client.get(f"/v1/projects/{pid}/decisions").json()
               ["decisions"]) == 1
    assert client.get("/v1/projects/NOPE/summary").status_code == 404


def test_summary_and_agent_not_approver(client, store):
    alice = _person(store, "alice06d")
    proj = projs.create_project(store, "DA006", "Du an F")
    projs.assign_member(store, proj["id"], alice, "PROJECT_MANAGER")
    now = utcnow_iso()
    store.execute(
        "INSERT INTO approvals (id, requester_person_id, action, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'approve', 'pending', ?, ?, 0)",
        (new_id(), alice, now, now),
    )
    summary = client.get(f"/v1/projects/{proj['id']}/summary").json()
    assert summary["project"]["code"] == "DA006"
    assert summary["team_size"] == 1
    assert summary["agent"]["final_approver"] is False
    assert len(summary["pending_approvals"]) == 1
    assert "mock-intelligence" in summary["brief"]
    # coordinator never decides approvals
    still = store.query_all(
        "SELECT status FROM approvals WHERE requester_person_id = ?",
        (alice,))
    assert {r["status"] for r in still} == {"pending"}


def test_projects_list(client, store):
    projs.create_project(store, "DA007", "Du an G")
    resp = client.get("/v1/projects")
    assert resp.status_code == 200
    assert "DA007" in {p["code"] for p in resp.json()["projects"]}
    one = client.get(
        f"/v1/projects/{projs.create_project(store, 'DA007', 'x')['id']}")
    assert one.status_code == 200
    assert client.get("/v1/projects/NOPE").status_code == 404


def test_migration_0004_applied(store):
    cols = [r["name"] for r in
            store.query_all("PRAGMA table_info(project_milestones)")]
    assert "title" in cols and "due_at" in cols
    row = store.query_one(
        "SELECT version FROM schema_migrations WHERE version = ?",
        ("0004_project_milestones",))
    assert row is not None
