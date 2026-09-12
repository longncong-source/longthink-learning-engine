"""Phase 10 tests: brief, aggregation, filtering, redaction, bans."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import enterprise as ent
from organization_core.api import create_org_app
from organization_core.auth import (
    AuthorizationError,
    ensure_policy,
    ensure_role,
    grant_permission_to_role,
)
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase10.sqlite3"))
    seed_dak(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    return TestClient(create_org_app(store))


def _person(store, code, dept="TCHC", pos="CV", name=None):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, name or code, now, now),
    )
    seat = store.query_one(
        "SELECT id FROM positions WHERE code = ?", (f"DAK-{dept}-{pos}",))
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, seat["id"], now, now),
    )
    return pid


def _role(store, person_id, role_code):
    rid = ensure_role(store, role_code, role_code)
    now = utcnow_iso()
    store.execute(
        "INSERT INTO person_roles (id, person_id, role_id, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
        (new_id(), person_id, rid, now, now),
    )


def _project(store, code, members=()):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    for person_id in members:
        store.execute(
            "INSERT INTO project_assignments (id, project_id, person_id,"
            " status, created_at, updated_at, is_deleted)"
            " VALUES (?, ?, ?, 'active', ?, ?, 0)",
            (new_id(), pid, person_id, now, now),
        )
    return pid


@pytest.fixture()
def world(store):
    grant_permission_to_role(store, "EXEC10", "EXECUTE", "task")
    admin = _person(store, "admin10", name="Admin Person")
    _role(store, admin, "ADMIN")
    grant_permission_to_role(store, "ADMIN", "ADMIN", "*")
    mgr = _person(store, "mgr10", dept="TCKT", pos="TP", name="Manager Person")
    _role(store, mgr, "EXEC10")
    staff = _person(store, "staff10", dept="TCKT", name="Staff Person")
    p1 = _project(store, "EP1", members=(mgr, staff))
    p2 = _project(store, "EP2", members=(admin,))
    now = utcnow_iso()
    store.execute(
        "INSERT INTO risks (id, project_id, title, severity, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'risk ep1', 'high', 'open', ?, ?, 0)",
        (new_id(), p1, now, now),
    )
    store.execute(
        "INSERT INTO approvals (id, requester_person_id, approver_person_id,"
        " action, resource, reason, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, 'EXECUTE', 'task', 'secret reason',"
        " 'pending', ?, ?, 0)",
        (new_id(), staff, mgr, now, now),
    )
    return {"admin": admin, "mgr": mgr, "staff": staff, "p1": p1, "p2": p2}


def test_agent_ensured(store, world):
    agent = ent.ensure_enterprise_agent(store)
    assert agent["name"] == "ENTERPRISE_AGENT"
    assert agent["config"]["final_approver"] is False
    assert "observe" in agent["config"]["allowed_verbs"]
    assert len(agent["config"]["banned_actions"]) == len(ent.BANNED_ACTIONS)


def test_executive_summary(client, world):
    resp = client.get("/v1/enterprise/overview",
                      params={"actor_person_id": world["admin"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["company"]["code"] == "DAK"
    assert body["is_admin_view"] is True
    assert body["department_count"] == 8
    assert body["project_count"] == 2
    brief = client.post("/v1/enterprise/brief",
                        json={"actor_person_id": world["admin"]}).json()
    assert "mock-intelligence" in brief["brief"]
    assert brief["top_risks"] == ["risk ep1"]
    assert client.get("/v1/enterprise/overview",
                      params={"actor_person_id": "ghost"}).status_code == 403


def test_cross_department_aggregation(client, world):
    health = client.get("/v1/enterprise/departments/health",
                        params={"actor_person_id": world["admin"]}).json()
    assert len(health["departments"]) == 8
    portfolio = client.get("/v1/enterprise/projects/portfolio",
                           params={"actor_person_id": world["admin"]}).json()
    assert {p["code"] for p in portfolio["projects"]} == {"EP1", "EP2"}
    resources = client.get("/v1/enterprise/resources",
                           params={"actor_person_id": world["admin"]}).json()
    assert resources["total_baseline"] >= 8
    assert resources["total_assigned"] >= 3


def test_permission_filtering(client, world):
    health = client.get("/v1/enterprise/departments/health",
                        params={"actor_person_id": world["mgr"]}).json()
    assert [d["code"] for d in health["departments"]] == ["TCKT"]
    portfolio = client.get("/v1/enterprise/projects/portfolio",
                           params={"actor_person_id": world["mgr"]}).json()
    assert [p["code"] for p in portfolio["projects"]] == ["EP1"]
    overview = client.get("/v1/enterprise/overview",
                          params={"actor_person_id": world["mgr"]}).json()
    assert overview["is_admin_view"] is False
    assert overview["project_count"] == 1


def test_sensitive_data_filtering(client, world):
    health = client.get("/v1/enterprise/departments/health",
                        params={"actor_person_id": world["mgr"]}).json()
    tckt = health["departments"][0]
    assert tckt["member_count"] == 2
    assert all("full_name" not in m for m in tckt["members"])
    admin_view = client.get("/v1/enterprise/departments/health",
                            params={"actor_person_id": world["admin"]}).json()
    names = [m.get("full_name") for d in admin_view["departments"]
             for m in d["members"]]
    assert "Manager Person" in names
    approvals = client.get("/v1/enterprise/approvals",
                           params={"actor_person_id": world["staff"]}).json()
    assert len(approvals["approvals"]) == 1
    assert "reason" not in approvals["approvals"][0]
    admin_appr = client.get("/v1/enterprise/approvals",
                            params={"actor_person_id": world["admin"]}).json()
    assert admin_appr["approvals"][0]["reason"] == "secret reason"


def test_banned_actions_never_autonomous(store, world):
    for action, resource in [("CREATE", "person"), ("DELETE", "person"),
                             ("EXECUTE", "contract"),
                             ("UPDATE", "org_authority"),
                             ("UPDATE", "security_policy"),
                             ("APPROVE", "payment")]:
        result = ent.enterprise_act(store, world["admin"], "execute",
                                    action, resource)
        assert result["allowed"] is False, (action, resource)
    assert ent.enterprise_act(store, world["admin"], "analyze")["allowed"]


def test_execution_needs_explicit_policy(store, world):
    refused = ent.enterprise_act(store, world["mgr"], "execute",
                                 "EXECUTE", "task",
                                 {"project_id": world["p1"]})
    assert refused["allowed"] is False
    ensure_policy(store, "ENTERPRISE_EXECUTION_ALLOW", "Allow", "allow",
                  {"actions": ["EXECUTE"], "resources": ["task"]})
    allowed = ent.enterprise_act(store, world["mgr"], "execute",
                                 "EXECUTE", "task",
                                 {"project_id": world["p1"]})
    assert allowed["allowed"] is True
    # ...but bans stay banned even with the policy in place
    still = ent.enterprise_act(store, world["admin"], "execute",
                               "EXECUTE", "contract")
    assert still["allowed"] is False
    with pytest.raises(AuthorizationError):
        ent.enterprise_act(store, "ghost", "observe")


def test_act_api(client, world):
    resp = client.post("/v1/enterprise/act", json={
        "actor_person_id": world["admin"], "verb": "execute",
        "action": "DELETE", "resource": "person"})
    assert resp.status_code == 403
    ok = client.post("/v1/enterprise/act", json={
        "actor_person_id": world["admin"], "verb": "coordinate"})
    assert ok.json()["allowed"] is True
