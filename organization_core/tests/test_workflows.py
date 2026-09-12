"""Phase 07 tests: state machine, HITL, escalation, expiry, idempotency."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import workflows as wf
from organization_core.api import create_org_app
from organization_core.auth import grant_permission_to_role
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore

PAST = "2000-01-01T00:00:00+00:00"
FUTURE = "2100-01-01T00:00:00+00:00"


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase07.sqlite3"))
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
    return pid


def _approver(store, code):
    from organization_core.auth import ensure_role

    pid = _person(store, code)
    rid = ensure_role(store, "APPROVER07", "Approver")
    now = utcnow_iso()
    store.execute(
        "INSERT INTO person_roles (id, person_id, role_id, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
        (new_id(), pid, rid, now, now),
    )
    return pid


@pytest.fixture()
def actors(store):
    grant_permission_to_role(store, "APPROVER07", "APPROVE", "*")
    return {"req": _person(store, "req07"),
            "boss": _approver(store, "boss07"),
            "big_boss": _approver(store, "big07")}


def test_transition_chain(store, actors):
    flow = wf.create_workflow(store, "WF07", "Procurement")
    inst = wf.start_instance(store, flow["id"], "purchase", "PO-1")
    assert inst["status"] == "DRAFT"
    for state in ("SUBMITTED", "IN_REVIEW", "APPROVED", "IN_PROGRESS",
                  "COMPLETED"):
        inst = wf.transition_instance(store, inst["id"], state,
                                      actors["boss"])
        assert inst["status"] == state
    same = wf.transition_instance(store, inst["id"], "COMPLETED")
    assert same["status"] == "COMPLETED"  # idempotent


def test_invalid_transition(store, actors):
    flow = wf.create_workflow(store, "WF07B", "Simple")
    inst = wf.start_instance(store, flow["id"])
    with pytest.raises(wf.WorkflowError):
        wf.transition_instance(store, inst["id"], "APPROVED")
    with pytest.raises(wf.WorkflowError):
        wf.transition_instance(store, inst["id"], "NOPE")
    with pytest.raises(LookupError):
        wf.transition_instance(store, "missing", "SUBMITTED")


def test_task_full_fields(store, actors):
    task = wf.create_task(
        store, "lap bao gia", owner_person_id=actors["req"],
        assignee_person_id=actors["boss"], priority="high",
        dependencies=["t-1"], source="chat")
    assert task["owner_person_id"] == actors["req"]
    assert task["priority"] == "high"
    updated = wf.update_task(store, task["id"], {"status": "in_progress"})
    assert updated["status"] == "in_progress"
    with pytest.raises(wf.WorkflowError):
        wf.update_task(store, task["id"], {"nope": 1})


def test_approval_idempotent_request(store, actors):
    first = wf.request_approval(
        store, actors["req"], "EXECUTE", "contract", "sign HĐ",
        approver_person_id=actors["boss"], idempotency_key="idem-1")
    assert first["policy_snapshot"]
    second = wf.request_approval(
        store, actors["req"], "EXECUTE", "contract", "sign HĐ again",
        approver_person_id=actors["boss"], idempotency_key="idem-1")
    assert second["id"] == first["id"]
    assert store.count("approvals", "idempotency_key = 'idem-1'") == 1


def test_approve_and_reject(store, actors):
    ok_item = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "run it",
        approver_person_id=actors["boss"])
    decided = wf.decide_approval(store, ok_item["id"], actors["boss"],
                                 "approved", "ok")
    assert decided["status"] == "approved"
    assert decided["decision"] == "approved"
    assert decided["decided_at"]
    repeat = wf.decide_approval(store, ok_item["id"], actors["boss"],
                                "approved")
    assert repeat["status"] == "approved"  # idempotent
    no_item = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "run that",
        approver_person_id=actors["boss"])
    denied = wf.decide_approval(store, no_item["id"], actors["boss"],
                                "rejected", "not now")
    assert denied["status"] == "rejected"


def test_approver_mismatch_and_unauthorized(store, actors):
    item = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "x",
        approver_person_id=actors["boss"])
    with pytest.raises(wf.WorkflowError):
        wf.decide_approval(store, item["id"], actors["big_boss"], "approved")
    stranger = _person(store, "stranger07")
    open_item = wf.request_approval(store, actors["req"], "EXECUTE", "task",
                                    "y")
    with pytest.raises(wf.WorkflowError):
        wf.decide_approval(store, open_item["id"], stranger, "approved")


def test_escalation(store, actors):
    item = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "needs bigger boss",
        approver_person_id=actors["boss"])
    moved = wf.escalate_approval(store, item["id"], actors["boss"],
                                 to_person_id=actors["big_boss"],
                                 reason="over limit")
    assert moved["approver_person_id"] == actors["big_boss"]
    decided = wf.decide_approval(store, item["id"], actors["big_boss"],
                                 "approved")
    assert decided["status"] == "approved"
    with pytest.raises(wf.WorkflowError):
        wf.escalate_approval(store, item["id"], actors["big_boss"],
                             to_person_id=actors["boss"])


def test_expired_approval(store, actors):
    item = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "late",
        approver_person_id=actors["boss"], expires_at=PAST)
    with pytest.raises(wf.ApprovalExpired):
        wf.decide_approval(store, item["id"], actors["boss"], "approved")
    row = store.query_one("SELECT status FROM approvals WHERE id = ?",
                          (item["id"],))
    assert row["status"] == "expired"
    item2 = wf.request_approval(
        store, actors["req"], "EXECUTE", "task", "also late",
        approver_person_id=actors["boss"], expires_at=PAST)
    assert wf.expire_overdue(store) >= 1
    row2 = store.query_one("SELECT status FROM approvals WHERE id = ?",
                           (item2["id"],))
    assert row2["status"] == "expired"


def test_hitl_consequential(store):
    assert wf.hitl_required(store, "EXECUTE", "contract") is True
    assert wf.hitl_required(store, "EXECUTE", "payment") is True
    assert wf.hitl_required(store, "UPDATE", "budget") is True
    assert wf.hitl_required(store, "UPDATE", "org_authority") is True
    assert wf.hitl_required(store, "UPDATE", "baseline") is True
    assert wf.hitl_required(store, "READ", "document") is False


def test_execute_once_then_duplicate(store, actors):
    item = wf.request_approval(
        store, actors["req"], "EXECUTE", "contract", "sign",
        approver_person_id=actors["boss"])
    with pytest.raises(wf.WorkflowError):
        wf.execute_consequential(store, item["id"], actors["req"])
    wf.decide_approval(store, item["id"], actors["boss"], "approved")
    first = wf.execute_consequential(store, item["id"], actors["req"])
    assert first["status"] == "executed"
    second = wf.execute_consequential(store, item["id"], actors["req"])
    assert second["status"] == "duplicate"
    assert second["task_id"] == first["task_id"]


def test_api_flow(client, store, actors):
    wf_resp = client.post("/v1/workflows",
                          json={"code": "WFAPI", "name": "API flow"})
    assert wf_resp.status_code == 201
    inst = client.post("/v1/workflow-instances", json={
        "workflow_id": wf_resp.json()["id"]}).json()
    bad = client.post(
        f"/v1/workflow-instances/{inst['id']}/transition",
        json={"to_state": "APPROVED"})
    assert bad.status_code == 422
    ok = client.post(
        f"/v1/workflow-instances/{inst['id']}/transition",
        json={"to_state": "SUBMITTED",
              "actor_person_id": actors["boss"]}).json()
    assert ok["status"] == "SUBMITTED"
    task = client.post("/v1/tasks", json={
        "title": "api task", "owner_person_id": actors["req"],
        "assignee_person_id": actors["boss"], "priority": "high",
        "dependencies": ["x"], "source": "api"}).json()
    assert task["priority"] == "high"
    listed = client.get("/v1/tasks",
                        params={"assignee": actors["boss"]}).json()
    assert len(listed["tasks"]) >= 1
    patched = client.patch(f"/v1/tasks/{task['id']}",
                           json={"status": "done"}).json()
    assert patched["status"] == "done"
    appr = client.post("/v1/approvals", json={
        "requested_by": actors["req"], "action": "EXECUTE",
        "resource": "payment", "reason": "pay vendor",
        "approver_person_id": actors["boss"],
        "idempotency_key": "api-idem-9", "expires_at": FUTURE}).json()
    dup = client.post("/v1/approvals", json={
        "requested_by": actors["req"], "action": "EXECUTE",
        "resource": "payment", "idempotency_key": "api-idem-9"}).json()
    assert dup["id"] == appr["id"]
    dec = client.post(f"/v1/approvals/{appr['id']}/decide", json={
        "approver_person_id": actors["boss"], "verdict": "approved"})
    assert dec.json()["status"] == "approved"
    exe1 = client.post(f"/v1/approvals/{appr['id']}/execute", json={
        "executor_person_id": actors["req"]}).json()
    exe2 = client.post(f"/v1/approvals/{appr['id']}/execute", json={
        "executor_person_id": actors["req"]}).json()
    assert exe1["status"] == "executed"
    assert exe2["status"] == "duplicate"
    esc = client.post("/v1/approvals", json={
        "requested_by": actors["req"], "action": "EXECUTE",
        "resource": "task",
        "approver_person_id": actors["boss"]}).json()
    moved = client.post(f"/v1/approvals/{esc['id']}/escalate", json={
        "by_person_id": actors["boss"],
        "to_person_id": actors["big_boss"]}).json()
    assert moved["approver_person_id"] == actors["big_boss"]
    old = client.post("/v1/approvals", json={
        "requested_by": actors["req"], "action": "EXECUTE",
        "resource": "task", "approver_person_id": actors["boss"],
        "expires_at": PAST}).json()
    gone = client.post(f"/v1/approvals/{old['id']}/decide", json={
        "approver_person_id": actors["boss"], "verdict": "approved"})
    assert gone.status_code == 410


def test_migration_0005_applied(store):
    task_cols = {r["name"] for r in
                 store.query_all("PRAGMA table_info(tasks)")}
    appr_cols = {r["name"] for r in
                 store.query_all("PRAGMA table_info(approvals)")}
    assert {"owner_person_id", "department_id", "dependencies",
            "source"} <= task_cols
    assert {"resource", "reason", "decision", "policy_snapshot",
            "idempotency_key", "expires_at"} <= appr_cols
