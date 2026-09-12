"""Phase 05 tests: 7 agents, routing, scope, cross-dept, enforcement."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from organization_core import assistant as assistant_service
from organization_core import department_agents as dept_agents
from organization_core.api import create_org_app
from organization_core.auth import AuthorizationError
from organization_core.models import new_id, utcnow_iso
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore

ROUTING_CASES = [
    ("chính sách lương và đào tạo nhân sự thế nào?", "TCHC_AGENT"),
    ("báo cáo tài chính và thuế quý này", "TCKT_AGENT"),
    ("điều khoản hợp đồng và đấu thầu gói mới", "KTHD_AGENT"),
    ("tiến độ thi công và nghiệm thu hạng mục", "KTGS_AGENT"),
    ("cơ hội đầu tư và tính khả thi dự án mới", "PTDA_AGENT"),
    ("bản vẽ thiết kế và giải pháp công nghệ", "TKCN_AGENT"),
    ("sự cố an toàn và đánh giá ISO môi trường", "AT_AGENT"),
]


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase05.sqlite3"))
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


def test_seven_agents_seeded(store):
    agents = dept_agents.ensure_department_agents(store)
    assert len(agents) == 7
    codes = {a["name"] for a in agents}
    assert codes == {f"{c}_AGENT" for c in dept_agents.AGENT_ORDER}
    for agent in agents:
        assert agent["kind"] == "department"
        assert agent["ref_type"] == "department"
        assert agent["department_id"]
        for key in dept_agents.REQUIRED_SPEC_KEYS:
            assert key in agent["config"], key
    again = dept_agents.ensure_department_agents(store)
    assert {a["id"] for a in again} == {a["id"] for a in agents}
    assert store.count("agents", "kind = 'department'") == 7


def test_agents_api(client):
    resp = client.get("/v1/department-agents")
    assert resp.status_code == 200
    assert len(resp.json()["agents"]) == 7
    one = client.get("/v1/department-agents/TCKT")
    assert one.status_code == 200
    body = one.json()
    assert body["name"] == "TCKT_AGENT"
    assert "finance" in body["config"]["responsibilities"]
    assert client.get("/v1/department-agents/NOPE").status_code == 404


@pytest.mark.parametrize("message,expected", ROUTING_CASES)
def test_correct_routing(store, message, expected):
    result = dept_agents.route_to_agent(store, message)
    assert result["agent_code"] == expected
    assert result["score"] > 0


def test_routing_api(client):
    resp = client.post("/v1/department-agents/route",
                       json={"message": "kế toán thuế và doanh thu"})
    assert resp.status_code == 200
    assert resp.json()["agent_code"] == "TCKT_AGENT"


def test_wrong_routing_rejected(store):
    finance_q = "hợp đồng và quyết toán chi phí"
    assert dept_agents.agent_handles(store, "KTHD", finance_q) is True
    assert dept_agents.agent_handles(store, "AT", finance_q) is False
    forced = dept_agents.route_to_agent(store, finance_q,
                                        candidates=["AT"])
    assert forced["agent_code"] is None
    assert forced["score"] == 0
    with pytest.raises(LookupError):
        dept_agents.agent_handles(store, "NOPE", finance_q)


def test_cross_department_coordinate(store, client):
    alice = _person(store, "alice05")
    resp = client.post("/v1/department-agents/coordinate", json={
        "actor_person_id": alice,
        "message": "đánh giá tiến độ thi công và an toàn công trường",
        "agents": ["KTGS", "AT"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["authorized"] is True
    assert {c["agent_code"] for c in body["contributions"]} == {
        "KTGS_AGENT", "AT_AGENT"}
    assert "KTGS_AGENT" in body["reply"] and "AT_AGENT" in body["reply"]
    audit = store.count("audit_events", "action = 'agent.coordinate'")
    assert audit >= 1


def test_coordinator_refuses_execution(store):
    alice = _person(store, "alice05b")
    result = dept_agents.coordinate(
        store, alice, "thực hiện ngay gói thầu này", agent_codes=["KTHD"])
    assert result["authorized"] is False
    assert result["contributions"] == []


def test_coordinator_unknown_actor(store):
    with pytest.raises(AuthorizationError):
        dept_agents.coordinate(store, "ghost", "hello finance",
                               agent_codes=["TCKT"])


def test_chat_routes_to_department_agent(client, store):
    alice = _person(store, "alice05c")
    aid = assistant_service.get_or_create_personal_assistant(
        store, alice)["id"]
    resp = client.post(f"/v1/assistants/{aid}/chat", json={
        "actor_person_id": alice,
        "message": "chính sách thuế thu nhập hiện nay thế nào?"})
    body = resp.json()
    assert body["intent"] == "question"
    assert body["routed_to"] == "TCKT_AGENT"
    assert "[TCKT_AGENT]" in body["reply"]
    assert "mock-intelligence" in body["reply"]


def test_agent_scope_definitions():
    for code, spec in dept_agents.AGENT_SPECS.items():
        assert spec["agent_code"] == f"{code}_AGENT"
        assert spec["mandate"]
        assert len(spec["responsibilities"]) >= 5
        assert spec["allowed_tools"]
        assert spec["knowledge_scope"]
        assert spec["routing_rules"]["keywords"]
        assert spec["approval_rules"].get("self_approve") is False
        assert spec["escalation_rules"].get("to") == "BGD"
