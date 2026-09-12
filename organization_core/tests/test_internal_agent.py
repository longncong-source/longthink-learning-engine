"""Phase 09 tests: gated dispatch, envelope, states, idempotency, audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import execution as exe
from organization_core.adapters import MockInternalAgentAdapter
from organization_core.api import create_org_app
from organization_core.auth import AuthorizationError, grant_permission_to_role
from organization_core.integration import CoreClientError
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


class FailingBackend(MockInternalAgentAdapter):
    def execute(self, action, payload):
        raise CoreClientError("http", "agent exploded", "cid")


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase09.sqlite3"))
    seed_dak(s)
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
        "SELECT id FROM positions WHERE code = 'DAK-TCHC-CV'")
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, pos["id"], now, now),
    )
    return pid


def _project(store, code):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    return pid


@pytest.fixture()
def world(store):
    grant_permission_to_role(store, "EXEC09", "EXECUTE", "task")
    from organization_core.auth import ensure_role

    rid = ensure_role(store, "EXEC09", "Exec")
    alice = _person(store, "alice09")
    bob = _person(store, "bob09")
    now = utcnow_iso()
    for pid in (alice,):
        store.execute(
            "INSERT INTO person_roles (id, person_id, role_id, created_at,"
            " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
            (new_id(), pid, rid, now, now),
        )
    p1 = _project(store, "EX1")
    for pid in (alice, bob):
        store.execute(
            "INSERT INTO project_assignments (id, project_id, person_id,"
            " status, created_at, updated_at, is_deleted)"
            " VALUES (?, ?, ?, 'active', ?, ?, 0)",
            (new_id(), p1, pid, now, now),
        )
    return {"alice": alice, "bob": bob, "p1": p1}


def test_envelope_shape(store, world):
    env = exe.build_envelope(store, world["alice"], "EXECUTE", "task",
                             task={"title": "t"}, project_id=world["p1"],
                             idempotency_key="k")
    assert set(env) == {"actor", "organization_context", "project_context",
                        "permission", "task", "action", "correlation_id",
                        "idempotency_key"}
    assert env["actor"]["actor_id"] == world["alice"]
    assert env["project_context"] == {"project_id": world["p1"]}
    assert env["idempotency_key"] == "k"
    assert "Agent" not in str(env)  # no personal data leaks


def test_execute_allowed_action(store, world):
    backend = MockInternalAgentAdapter()
    record, duplicate = exe.submit_execution(
        store, backend, world["alice"], "EXECUTE", "task",
        task={"title": "do it"}, project_id=world["p1"],
        idempotency_key="allow-1")
    assert duplicate is False
    assert record["status"] == "COMPLETED"
    assert len(backend.executed) == 1
    trail = [r["action"] for r in store.query_all(
        "SELECT action FROM audit_events WHERE entity_id = ? ORDER BY rowid",
        (record["id"],))]
    assert trail == ["execution.accepted", "execution.running",
                     "execution.completed"]


def test_deny_unauthorized_never_dispatched(store, world):
    backend = MockInternalAgentAdapter()
    with pytest.raises(AuthorizationError):
        exe.submit_execution(store, backend, world["bob"], "EXECUTE", "task",
                             project_id=world["p1"],
                             idempotency_key="deny-1")
    assert backend.executed == []
    assert store.count("agent_executions",
                       "idempotency_key = 'deny-1'") == 0
    assert store.count("audit_events",
                       "action = 'execution.denied'") >= 1


def test_duplicate_request_single_execution(store, world):
    backend = MockInternalAgentAdapter()
    first, dup1 = exe.submit_execution(
        store, backend, world["alice"], "EXECUTE", "task",
        project_id=world["p1"], idempotency_key="dup-9")
    second, dup2 = exe.submit_execution(
        store, backend, world["alice"], "EXECUTE", "task",
        project_id=world["p1"], idempotency_key="dup-9")
    assert dup1 is False and dup2 is True
    assert first["id"] == second["id"]
    assert len(backend.executed) == 1


def test_failed_execution_recorded(store, world):
    record, _ = exe.submit_execution(
        store, FailingBackend(), world["alice"], "EXECUTE", "task",
        project_id=world["p1"], idempotency_key="fail-9")
    assert record["status"] == "FAILED"
    assert record["failed"] is True
    assert "exploded" in (record["error"] or "")


def test_status_polling_and_cancel(store, world):
    backend = MockInternalAgentAdapter()
    record, _ = exe.submit_execution(
        store, backend, world["alice"], "EXECUTE", "task",
        project_id=world["p1"], idempotency_key="poll-9")
    polled = exe.poll_execution(store, backend, record["id"])
    assert polled["status"] == "COMPLETED"
    with pytest.raises(exe.WorkflowError):
        exe.cancel_execution(store, backend, record["id"], world["alice"])
    # simulate an async pending execution, then cancel it
    now = utcnow_iso()
    pending_id = new_id()
    store.execute(
        "INSERT INTO agent_executions (id, actor_person_id, action, resource,"
        " backend_task_id, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'EXECUTE', 'task', 'mock-exec-1', 'RUNNING', ?, ?, 0)",
        (pending_id, world["alice"], now, now),
    )
    cancelled = exe.cancel_execution(store, backend, pending_id,
                                     world["alice"])
    assert cancelled["status"] == "CANCELLED"
    with pytest.raises(LookupError):
        exe.get_execution(store, "missing")


def test_local_bridge_mapping():
    seen = {}

    def runner(question, project_id):
        seen["q"] = question
        seen["p"] = project_id

        class Result:
            answer = "done via first brain"

        return Result()

    adapter = exe.build_internal_adapter("local", runner=runner)
    out = adapter.execute("EXECUTE.task", {
        "task": {"question": "summarize"}, "project_context": {"p": 1},
        "project_id": None, "action": {}})
    assert out["backend"] == "local-first-brain"
    assert out["status"] == "completed"
    assert seen["q"] == "summarize"
    assert adapter.cancel("x")["status"] == "not_supported"
    assert exe.build_internal_adapter("mock").execute("a", {})["backend"] == (
        "mock")


def test_api_executions(client, store, world):
    created = client.post("/v1/executions", json={
        "actor_person_id": world["alice"], "action": "EXECUTE",
        "resource": "task", "task": {"title": "api job"},
        "project_id": world["p1"], "idempotency_key": "api-exe-1"})
    assert created.status_code == 201
    assert created.json()["execution"]["status"] == "COMPLETED"
    dup = client.post("/v1/executions", json={
        "actor_person_id": world["alice"], "action": "EXECUTE",
        "resource": "task", "project_id": world["p1"],
        "idempotency_key": "api-exe-1"})
    assert dup.status_code == 200
    assert dup.json()["duplicate"] is True
    denied = client.post("/v1/executions", json={
        "actor_person_id": world["bob"], "action": "EXECUTE",
        "resource": "task", "project_id": world["p1"]})
    assert denied.status_code == 403
    eid = created.json()["execution"]["id"]
    polled = client.get(f"/v1/executions/{eid}")
    assert polled.json()["status"] == "COMPLETED"
    assert client.get("/v1/executions/missing").status_code == 404
    cancel_done = client.post(f"/v1/executions/{eid}/cancel", json={
        "actor_person_id": world["alice"]})
    assert cancel_done.status_code == 422


def test_migration_0006_applied(store):
    cols = {r["name"] for r in
            store.query_all("PRAGMA table_info(agent_executions)")}
    assert {"idempotency_key", "envelope", "permission_snapshot",
            "correlation_id", "status"} <= cols
