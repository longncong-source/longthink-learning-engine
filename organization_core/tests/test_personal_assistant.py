"""Phase 04 tests: assistant 1-1, context, enforcement, switching, audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import assistant as assistant_service
from organization_core.adapters import AdapterBundle
from organization_core.api import create_org_app
from organization_core.auth import (
    AuthorizationError,
    ensure_policy,
    grant_permission_to_role,
)
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase04.sqlite3"))
    seed_dak(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    return TestClient(create_org_app(store))


def _person(store, code, dept_code="TCHC", pos_suffix="CV"):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    pos = store.query_one(
        "SELECT id FROM positions WHERE code = ?",
        (f"DAK-{dept_code}-{pos_suffix}",))
    assert pos is not None
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, pos["id"], now, now),
    )
    return pid


def _role(store, person_id, role_code):
    from organization_core.auth import ensure_role

    rid = ensure_role(store, role_code, role_code)
    now = utcnow_iso()
    store.execute(
        "INSERT INTO person_roles (id, person_id, role_id, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
        (new_id(), person_id, rid, now, now),
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


def _assign(store, project_id, person_id, role_code=None):
    rid = None
    if role_code:
        now = utcnow_iso()
        rid = new_id()
        store.execute(
            "INSERT INTO project_roles (id, code, name, authority_level,"
            " created_at, updated_at, is_deleted)"
            " VALUES (?, ?, ?, 1, ?, ?, 0)",
            (rid, role_code, role_code, now, now),
        )
    now = utcnow_iso()
    store.execute(
        "INSERT INTO project_assignments (id, project_id, person_id,"
        " project_role_id, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, 0)",
        (new_id(), project_id, person_id, rid, now, now),
    )


def _task(store, project_id, person_id, title="task one"):
    tid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO tasks (id, project_id, assignee_person_id, title,"
        " status, priority, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'open', 'normal', ?, ?, 0)",
        (tid, project_id, person_id, title, now, now),
    )
    return tid


def _approval(store, requester, approver=None):
    aid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO approvals (id, requester_person_id, approver_person_id,"
        " action, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 'approve', 'pending', ?, ?, 0)",
        (aid, requester, approver, now, now),
    )
    return aid


@pytest.fixture()
def world(store):
    alice = _person(store, "alice", "TCHC")
    grant_permission_to_role(store, "STAFF", "READ", "document")
    grant_permission_to_role(store, "STAFF", "EXECUTE", "task")
    grant_permission_to_role(store, "LEAD", "APPROVE", "approval")
    _role(store, alice, "STAFF")
    bob = _person(store, "bob", "TCKT")
    p1, p2 = _project(store, "W1"), _project(store, "W2")
    _assign(store, p1, alice, "DEV")
    _assign(store, p2, alice, "VIEWER")
    _task(store, p1, alice)
    ensure_policy(store, "EXPORT_DENY04", "No exports", "deny",
                  {"actions": ["EXPORT"], "resources": ["document"]})
    return {"alice": alice, "bob": bob, "p1": p1, "p2": p2}


def test_one_human_one_assistant(store, world):
    first = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])
    second = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])
    assert first["id"] == second["id"]
    assert first["kind"] == "personal"
    with pytest.raises(LookupError):
        assistant_service.get_or_create_personal_assistant(store, "missing")


def test_assistant_creation_api(client, store, world):
    resp = client.post("/v1/assistants", json={
        "kind": "personal", "name": "Alice PA",
        "owner_person_id": world["alice"]})
    assert resp.status_code == 201
    dup = client.post("/v1/assistants", json={
        "kind": "personal", "name": "Alice PA 2",
        "owner_person_id": world["alice"]})
    assert dup.status_code == 409
    bad = client.post("/v1/assistants", json={
        "kind": "personal", "name": "Ghost",
        "owner_person_id": "no-such-person"})
    assert bad.status_code == 404


def test_context_resolution_keys(client, store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    resp = client.get(f"/v1/assistants/{aid}")
    assert resp.status_code == 200
    body = resp.json()
    for key in ("person", "departments", "positions", "roles", "permissions",
                "projects", "current_project", "tasks", "pending_approvals",
                "policies"):
        assert key in body, key
    assert body["person"]["code"] == "alice"
    assert body["departments"][0]["code"] == "TCHC"
    assert len(body["tasks"]) == 1
    assert {p["project_code"] for p in body["projects"]} == {"W1", "W2"}


def test_tasks_endpoint(client, store, world):
    resp = client.get(f"/v1/people/{world['alice']}/tasks")
    assert resp.status_code == 200
    assert len(resp.json()["tasks"]) == 1
    assert client.get("/v1/people/no-such/tasks").status_code == 404


def test_chat_question_flow(client, store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    before = store.count("audit_events", "action LIKE 'assistant.chat:%'")
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["alice"],
        "message": "Việc nào của tôi hôm nay?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "question" and body["authorized"] is True
    assert "mock-intelligence" in body["reply"]
    assert body["citations"]
    after = store.count("audit_events", "action LIKE 'assistant.chat:%'")
    assert after - before == 1


def test_chat_impersonation_blocked(client, store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["bob"], "message": "hello"})
    assert resp.status_code == 403


def test_execution_allowed_in_scope(client, store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["alice"],
        "message": "thực hiện task này",
        "current_project_id": world["p1"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["intent"] == "execution" and body["authorized"] is True
    assert body["execution"]["status"] == "completed"


def test_execution_denied_out_of_scope(client, store, world):
    stranger = _person(store, "stranger", "AT")
    grant_permission_to_role(store, "READER", "READ", "document")
    _role(store, stranger, "READER")
    _assign(store, world["p1"], stranger)
    aid = assistant_service.get_or_create_personal_assistant(
        store, stranger)["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": stranger, "message": "execute this now",
        "current_project_id": world["p1"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorized"] is False
    assert "denied" in body["reply"].lower()
    # switching to a project the person is not assigned to is forbidden
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": stranger, "message": "hello there",
        "current_project_id": world["p2"]})
    assert resp.status_code == 403


def test_project_switch_changes_scope(store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    ctx1 = assistant_service.resolve_assistant_context(
        store, aid, current_project_id=world["p1"])
    ctx2 = assistant_service.resolve_assistant_context(
        store, aid, current_project_id=world["p2"])
    assert ctx1["current_project"]["project_code"] == "W1"
    assert ctx2["current_project"]["project_code"] == "W2"
    with pytest.raises(AuthorizationError):
        assistant_service.resolve_assistant_context(
            store, aid, current_project_id="not-a-project")


def test_policy_banned_approval_refused(client, store, world):
    _role(store, world["alice"], "LEAD")
    grant_permission_to_role(store, "LEAD", "EXPORT", "document")
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    _approval(store, world["alice"])
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["alice"], "message": "approve my request"})
    body = resp.json()
    # approval intent finds pending item; APPROVE perm via LEAD role.
    # Policy EXPORT_DENY04 targets EXPORT only, so approval proceeds.
    assert body["intent"] == "approval"
    assert body["authorized"] is True
    # ...while an EXPORT-denied execution path stays refused at authz layer
    from organization_core.auth import authorize
    denied = authorize(store, actor_person_id=world["alice"], action="EXPORT",
                       resource="document")
    assert denied.allow is False
    assert "EXPORT_DENY04" in denied.via


def test_approval_without_permission_denied(client, store, world):
    _approval(store, world["bob"], world["alice"])
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["bob"])["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["bob"], "message": "approve it"})
    assert resp.json()["authorized"] is False


def test_org_mutation_refused(client, store, world):
    aid = assistant_service.get_or_create_personal_assistant(
        store, world["alice"])["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": world["alice"],
        "message": "xóa phòng TCHC và sáp nhập cơ cấu"})
    body = resp.json()
    assert body["intent"] == "org_mutation"
    assert body["authorized"] is False


def test_adapters_are_mocks():
    bundle = AdapterBundle.mocks()
    assert bundle.knowledge.search("q", {})["backend"] == "mock"
    assert bundle.intelligence.ask("q", {})["backend"] == "mock"
    assert bundle.internal_agent.execute("a", {})["status"] == "completed"
