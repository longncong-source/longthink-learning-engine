"""Phase 02 tests: RBAC/ABAC matrix, delegation, escalation, audit, migration."""

from __future__ import annotations

import pytest

from organization_core.auth import (
    AuthContext,
    AuthorizationError,
    authorize,
    create_delegation,
    ensure_policy,
    grant_permission_to_role,
    grant_role,
)
from organization_core.models import new_id, utcnow_iso
from organization_core.store import OrganizationStore

PAST = "2000-01-01T00:00:00+00:00"
FUTURE = "2100-01-01T00:00:00+00:00"


@pytest.fixture()
def org(tmp_path):
    store = OrganizationStore(str(tmp_path / "org-phase02.sqlite3"))
    store.init_schema()
    yield store
    store.close()


def _company(store, code):
    cid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO companies (id, code, name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (cid, code, code, now, now),
    )
    return cid


def _dept(store, company_id, code):
    did = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO departments (id, company_id, code, name, dept_type,"
        " status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'functional', 'active', ?, ?, 0)",
        (did, company_id, code, code, now, now),
    )
    return did


def _position(store, dept_id, code):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO positions (id, department_id, code, title, level,"
        " authority_scope, headcount_baseline, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, ?, 'staff', '{}', 1, ?, ?, 0)",
        (pid, dept_id, code, code, now, now),
    )
    return pid


def _person(store, code, status="active"):
    pid = new_id()
    now = utcnow_iso()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, 0)",
        (pid, code, code, status, now, now),
    )
    return pid


def _seat(store, person_id, position_id):
    now = utcnow_iso()
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), person_id, position_id, now, now),
    )


def _role_grant(store, person_id, role_code):
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


def _assign(store, project_id, person_id):
    now = utcnow_iso()
    store.execute(
        "INSERT INTO project_assignments (id, project_id, person_id, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (new_id(), project_id, person_id, now, now),
    )


@pytest.fixture()
def matrix(org):
    c1 = _company(org, "C1")
    d1 = _dept(org, c1, "D1")
    d2 = _dept(org, c1, "D2")
    _seat(org, _person(org, "pos-holder-tmp"), _position(org, d1, "TMP"))
    pos_d1 = _position(org, d1, "POS-D1")
    pos_d2 = _position(org, d2, "POS-D2")
    emp = _person(org, "emp")
    mgr = _person(org, "mgr")
    member = _person(org, "member")
    outsider = _person(org, "outsider")
    admin = _person(org, "admin")
    ghost = _person(org, "inactive", status="inactive")
    for pid, pos in ((emp, pos_d1), (mgr, pos_d1), (member, pos_d1),
                     (outsider, pos_d1), (admin, pos_d1)):
        _seat(org, pid, pos)
    grant_permission_to_role(org, "EMP", "READ", "document")
    grant_permission_to_role(org, "MGR", "READ", "document")
    grant_permission_to_role(org, "MGR", "APPROVE", "approval")
    grant_permission_to_role(org, "MGR", "EXPORT", "document")
    grant_permission_to_role(org, "MEMBER", "EXECUTE", "task")
    grant_permission_to_role(org, "ADMIN", "ADMIN", "*")
    grant_permission_to_role(org, "ADMIN", "ASSIGN", "role")
    for pid, role in ((emp, "EMP"), (mgr, "MGR"), (member, "MEMBER"),
                      (admin, "ADMIN")):
        _role_grant(org, pid, role)
    p1 = _project(org, "P1")
    p2 = _project(org, "P2")
    _assign(org, p1, member)
    ensure_policy(org, "ADMIN_OVERRIDE", "Admin override", "allow",
                  {"admin_override": True})
    ensure_policy(org, "EXPORT_DENY", "No exports", "deny",
                  {"actions": ["EXPORT"], "resources": ["document"]})
    ensure_policy(org, "APPROVE_GATE", "Approval gate", "require_approval",
                  {"actions": ["APPROVE"], "resources": ["approval"]})
    return {
        "store": org, "c1": c1, "d1": d1, "d2": d2, "pos_d2": pos_d2,
        "emp": emp, "mgr": mgr, "member": member, "outsider": outsider,
        "admin": admin, "ghost": ghost, "p1": p1, "p2": p2,
    }


def test_employee_read_own_department(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["emp"],
                  action="READ", resource="document",
                  ctx=AuthContext(department_id=matrix["d1"]))
    assert d.allow and d.via == "role:EMP"


def test_manager_approve_with_approval_granted(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["mgr"],
                  action="APPROVE", resource="approval",
                  ctx=AuthContext(department_id=matrix["d1"],
                                  approval_granted=True))
    assert d.allow


def test_manager_approve_gated_without_grant(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["mgr"],
                  action="APPROVE", resource="approval",
                  ctx=AuthContext(department_id=matrix["d1"]))
    assert not d.allow and "approval" in d.reason


def test_project_role_execute(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["member"],
                  action="EXECUTE", resource="task",
                  ctx=AuthContext(project_id=matrix["p1"]))
    assert d.allow


def test_unauthorized_department_access(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["emp"],
                  action="READ", resource="document",
                  ctx=AuthContext(department_id=matrix["d2"]))
    assert not d.allow and "department" in d.reason


def test_cross_project_denial(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["member"],
                  action="EXECUTE", resource="task",
                  ctx=AuthContext(project_id=matrix["p2"]))
    assert not d.allow and "project" in d.reason


def test_deny_by_default(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["outsider"],
                  action="READ", resource="document",
                  ctx=AuthContext(department_id=matrix["d1"]))
    assert not d.allow and "no permission" in d.reason


def test_unknown_action_denied(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["admin"],
                  action="TELEPORT", resource="document")
    assert not d.allow


def test_inactive_actor_denied(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["ghost"],
                  action="READ", resource="document")
    assert not d.allow and "not active" in d.reason


def test_unknown_actor_denied(matrix):
    d = authorize(matrix["store"], actor_person_id="no-such-id",
                  action="READ", resource="document")
    assert not d.allow and "unknown actor" in d.reason


def test_admin_override(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["admin"],
                  action="ADMIN", resource="company")
    assert d.allow and d.via == "policy:ADMIN_OVERRIDE"


def test_deny_policy_beats_permission(matrix):
    d = authorize(matrix["store"], actor_person_id=matrix["mgr"],
                  action="EXPORT", resource="document",
                  ctx=AuthContext(department_id=matrix["d1"]))
    assert not d.allow and "EXPORT_DENY" in d.via


def test_cross_company_denied(matrix):
    other = _company(matrix["store"], "OTHER")
    d = authorize(matrix["store"], actor_person_id=matrix["emp"],
                  action="READ", resource="document",
                  ctx=AuthContext(company_id=other))
    assert not d.allow and "cross-company" in d.reason


def test_valid_delegation_allows(matrix):
    create_delegation(
        matrix["store"], authorized_by=matrix["mgr"],
        from_person_id=matrix["mgr"], to_person_id=matrix["emp"],
        scope={"actions": ["APPROVE"], "resources": ["approval"],
               "department_id": matrix["d1"]},
        effective_from=PAST, effective_to=FUTURE, reason="cover leave",
    )
    d = authorize(matrix["store"], actor_person_id=matrix["emp"],
                  action="APPROVE", resource="approval",
                  ctx=AuthContext(department_id=matrix["d1"],
                                  approval_granted=True))
    assert d.allow and d.via.startswith("delegation:")


def test_expired_delegation_denied(matrix):
    create_delegation(
        matrix["store"], authorized_by=matrix["mgr"],
        from_person_id=matrix["mgr"], to_person_id=matrix["outsider"],
        scope={"actions": ["READ"], "resources": ["document"]},
        effective_from=PAST, effective_to=PAST, reason="old cover",
    )
    d = authorize(matrix["store"], actor_person_id=matrix["outsider"],
                  action="READ", resource="document",
                  ctx=AuthContext(department_id=matrix["d1"]))
    assert not d.allow and "no permission" in d.reason


def test_grant_role_by_admin(matrix):
    d = grant_role(matrix["store"], authorized_by=matrix["admin"],
                   person_id=matrix["outsider"], role_code="EMP")
    assert d.allow
    check = authorize(matrix["store"], actor_person_id=matrix["outsider"],
                      action="READ", resource="document",
                      ctx=AuthContext(department_id=matrix["d1"]))
    assert check.allow


def test_grant_role_by_employee_blocked(matrix):
    with pytest.raises(AuthorizationError):
        grant_role(matrix["store"], authorized_by=matrix["emp"],
                   person_id=matrix["outsider"], role_code="EMP")


def test_agent_grant_blocked(matrix):
    with pytest.raises(AuthorizationError):
        grant_role(matrix["store"], authorized_by=matrix["admin"],
                   person_id=matrix["outsider"], role_code="EMP",
                   actor_type="agent")


def test_self_grant_admin_blocked(matrix):
    with pytest.raises(AuthorizationError):
        grant_role(matrix["store"], authorized_by=matrix["mgr"],
                   person_id=matrix["mgr"], role_code="ADMIN")


def test_foreign_delegation_by_nonholder_blocked(matrix):
    with pytest.raises(AuthorizationError):
        create_delegation(
            matrix["store"], authorized_by=matrix["outsider"],
            from_person_id=matrix["mgr"], to_person_id=matrix["outsider"],
            scope={"actions": ["APPROVE"], "resources": ["approval"]},
            reason="escalation attempt",
        )


def test_decisions_are_audited(matrix):
    before = matrix["store"].count("audit_events", "action LIKE 'authorize:%'")
    authorize(matrix["store"], actor_person_id=matrix["emp"],
              action="READ", resource="document",
              ctx=AuthContext(department_id=matrix["d1"]))
    authorize(matrix["store"], actor_person_id=matrix["emp"],
              action="DELETE", resource="company")
    after = matrix["store"].count("audit_events", "action LIKE 'authorize:%'")
    assert after - before == 2


def test_migration_0002_reason_column_and_idempotent(org):
    cols = [r["name"] for r in
            org.query_all("PRAGMA table_info(delegations)")]
    assert "reason" in cols
    row = org.query_one(
        "SELECT version FROM schema_migrations WHERE version = ?",
        ("0002_delegation_reason",),
    )
    assert row is not None
    org.init_schema()  # re-run must stay idempotent
    cols = [r["name"] for r in
            org.query_all("PRAGMA table_info(delegations)")]
    assert "reason" in cols
