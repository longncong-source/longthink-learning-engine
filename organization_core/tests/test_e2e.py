"""Phase 12 E2E: user -> assistant -> context -> authz -> agents ->
intelligence/knowledge -> internal agent -> audit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import assistant as assistant_service
from organization_core import observability as obs
from organization_core import workflows as wf
from organization_core.api import create_org_app
from organization_core.auth import ensure_role, grant_permission_to_role
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-e2e.sqlite3"))
    seed_dak(s)
    yield s
    s.close()


@pytest.fixture()
def client(store):
    obs.reset()
    return TestClient(create_org_app(store))


def _person(store, code, dept="KTGS"):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, code, now, now),
    )
    seat = store.query_one(
        "SELECT id FROM positions WHERE code = ?", (f"DAK-{dept}-KS",))
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), pid, seat["id"], now, now),
    )
    return pid


def test_full_scenario(client, store):
    grant_permission_to_role(store, "ENG", "EXECUTE", "task")
    grant_permission_to_role(store, "ENG", "READ", "document")
    grant_permission_to_role(store, "CHIEF", "APPROVE", "payment")
    emp = _person(store, "e2e-emp")
    mgr = _person(store, "e2e-mgr")
    for pid, role in ((emp, "ENG"), (mgr, "CHIEF")):
        rid = ensure_role(store, role, role)
        now = utcnow_iso()
        store.execute(
            "INSERT INTO person_roles (id, person_id, role_id, created_at,"
            " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
            (new_id(), pid, rid, now, now),
        )
    proj = new_id()
    pid = proj
    now = utcnow_iso()
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, 'E2E', 'E2E Project', 'active', ?, ?, 0)",
        (pid, now, now),
    )
    for person in (emp, mgr):
        store.execute(
            "INSERT INTO project_assignments (id, project_id, person_id,"
            " status, created_at, updated_at, is_deleted)"
            " VALUES (?, ?, ?, 'active', ?, ?, 0)",
            (new_id(), pid, person, now, now),
        )

    # 1-2. Personal Assistant + organization context
    aid = assistant_service.get_or_create_personal_assistant(store, emp)["id"]
    ctx = client.get(f"/v1/people/{emp}/context").json()
    assert ctx["company"]["code"] == "DAK"
    assert ctx["projects"][0]["project_code"] == "E2E"

    # 3-4. Authorization + Department agent routing via chat
    chat = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": emp,
        "message": "tiến độ thi công và an toàn thế nào?",
        "current_project_id": pid}).json()
    assert chat["authorized"] is True
    assert chat["routed_to"] in ("KTGS_AGENT", "AT_AGENT")

    # 5. Cross-department coordination
    coord = client.post("/v1/department-agents/coordinate", json={
        "actor_person_id": emp,
        "message": "tiến độ thi công và an toàn công trường",
        "agents": ["KTGS", "AT"]}).json()
    assert coord["authorized"] is True
    assert len(coord["contributions"]) == 2

    # 6-7. Intelligence/Knowledge (mock) -> Internal Agent after approval
    appr = wf.request_approval(store, emp, "EXECUTE", "payment", "pay vendor",
                               approver_person_id=mgr,
                               idempotency_key="e2e-pay-1")
    decided = wf.decide_approval(store, appr["id"], mgr, "approved")
    assert decided["status"] == "approved"
    first = wf.execute_consequential(store, appr["id"], emp)
    assert first["status"] == "executed"
    assert wf.execute_consequential(store, appr["id"], emp)["status"] == (
        "duplicate")

    # 8. Enterprise brief aggregates the same company state
    brief = client.post("/v1/enterprise/brief",
                        json={"actor_person_id": mgr}).json()
    assert brief["company"]["code"] == "DAK"

    # 9. Audit trail covers every layer
    actions = {r["action"] for r in store.query_all(
        "SELECT DISTINCT action FROM audit_events")}
    for expected in ("assistant.chat:question", "agent.coordinate",
                     "approval.request", "approval.approved",
                     "consequential.executed"):
        assert expected in actions, expected

    # Observability: requests counted, tracing header present
    metrics = client.get("/v1/metrics").json()
    assert metrics["counters"]
    assert any(k.startswith("org_request_latency_seconds")
               for k in metrics["latencies"])
    ready = client.get("/ready").json()
    assert ready == {"ready": True, "checks": {"database": True,
                                               "schema": True}}
    traced = client.get("/health", headers={"X-Request-ID": "e2e-rid"})
    assert traced.headers["X-Request-ID"] == "e2e-rid"
