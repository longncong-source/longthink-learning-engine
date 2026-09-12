"""Phase 01 tests: migration up/down, constraints, relationships, DAK seed."""

from __future__ import annotations

import sqlite3

import pytest

from organization_core.models import new_id, utcnow_iso
from organization_core.seed import DEPARTMENTS, seed_dak
from organization_core.store import OrganizationStore

EXPECTED_TABLES = {
    "companies",
    "departments",
    "teams",
    "positions",
    "persons",
    "roles",
    "permissions",
    "role_permissions",
    "person_roles",
    "person_positions",
    "delegations",
    "projects",
    "project_roles",
    "project_assignments",
    "tasks",
    "workflows",
    "workflow_instances",
    "approvals",
    "assistants",
    "agents",
    "policies",
    "audit_events",
    "risks",
    "issues",
    "decisions",
}


@pytest.fixture()
def store(tmp_path):
    s = OrganizationStore(str(tmp_path / "org-phase01.sqlite3"))
    s.init_schema()
    yield s
    s.close()


def _ids(store: OrganizationStore, table: str, code: str) -> str:
    row = store.query_one(f"SELECT id FROM {table} WHERE code = ?", (code,))
    assert row is not None
    return row["id"]


def test_migration_up_creates_all_tables(store):
    names = set(store.table_names())
    missing = EXPECTED_TABLES - names
    assert not missing, f"missing tables: {missing}"


def test_migration_down_and_reup(store):
    store.drop_all()
    names = set(store.table_names())
    assert not (EXPECTED_TABLES & names), "drop_all must remove org tables"
    store.init_schema()
    names = set(store.table_names())
    assert not (EXPECTED_TABLES - names)
    # idempotent re-run
    store.init_schema()


def test_entity_constraints_unique_notnull(store):
    now = utcnow_iso()
    cid = new_id()
    store.execute(
        "INSERT INTO companies (id, code, name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'C1', 'C One', 'active', ?, ?, 0)",
        (cid, now, now),
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.execute(
            "INSERT INTO companies (id, code, name, status, created_at,"
            " updated_at, is_deleted) VALUES (?, 'C1', 'dup', 'active', ?, ?, 0)",
            (new_id(), now, now),
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.execute(
            "INSERT INTO departments (id, company_id, code, name, dept_type,"
            " status, created_at, updated_at, is_deleted)"
            " VALUES (?, 'missing-company', 'X', 'X', 'functional', 'active',"
            " ?, ?, 0)",
            (new_id(), now, now),
        )


def test_relationship_company_department_team_person_assistant(store):
    now = utcnow_iso()
    cid, did, tid, pid = new_id(), new_id(), new_id(), new_id()
    store.execute(
        "INSERT INTO companies (id, code, name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'REL-C', 'Rel', 'active', ?, ?, 0)",
        (cid, now, now),
    )
    store.execute(
        "INSERT INTO departments (id, company_id, code, name, dept_type,"
        " status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'REL-D', 'Rel D', 'functional', 'active', ?, ?, 0)",
        (did, cid, now, now),
    )
    store.execute(
        "INSERT INTO teams (id, department_id, code, name, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'REL-T', 'Rel T', 'active', ?, ?, 0)",
        (tid, did, now, now),
    )
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'REL-P', 'Test Person',"
        " 'active', ?, ?, 0)",
        (pid, now, now),
    )
    aid = new_id()
    store.execute(
        "INSERT INTO assistants (id, kind, name, owner_person_id,"
        " department_id, project_id, config, status, created_at, updated_at,"
        " is_deleted) VALUES (?, 'personal', 'Rel Assistant', ?, ?, NULL,"
        " '{}', 'active', ?, ?, 0)",
        (aid, pid, did, now, now),
    )
    row = store.query_one(
        "SELECT a.name, p.code AS person, d.code AS dept "
        "FROM assistants a JOIN persons p ON p.id = a.owner_person_id "
        "JOIN departments d ON d.id = a.department_id WHERE a.id = ?",
        (aid,),
    )
    assert row["person"] == "REL-P"
    assert row["dept"] == "REL-D"


def test_person_position_and_role_are_independent(store):
    now = utcnow_iso()
    cid, did = new_id(), new_id()
    pos_id, person_id, role_id, perm_id = new_id(), new_id(), new_id(), new_id()
    store.execute(
        "INSERT INTO companies (id, code, name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'PP-C', 'PP', 'active', ?, ?, 0)",
        (cid, now, now),
    )
    store.execute(
        "INSERT INTO departments (id, company_id, code, name, dept_type,"
        " status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, 'PP-D', 'PP D', 'functional', 'active', ?, ?, 0)",
        (did, cid, now, now),
    )
    store.execute(
        "INSERT INTO positions (id, department_id, code, title, level,"
        " authority_scope, headcount_baseline, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, 'PP-POS', 'Pos', 'staff', '{}', 1, ?, ?, 0)",
        (pos_id, did, now, now),
    )
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'PP-P', 'PP Person', 'active',"
        " ?, ?, 0)",
        (person_id, now, now),
    )
    store.execute(
        "INSERT INTO person_positions (id, person_id, position_id, is_primary,"
        " created_at, updated_at, is_deleted) VALUES (?, ?, ?, 1, ?, ?, 0)",
        (new_id(), person_id, pos_id, now, now),
    )
    store.execute(
        "INSERT INTO roles (id, code, name, created_at, updated_at,"
        " is_deleted) VALUES (?, 'PP-R', 'PP Role', ?, ?, 0)",
        (role_id, now, now),
    )
    store.execute(
        "INSERT INTO permissions (id, code, action, resource, created_at,"
        " updated_at, is_deleted) VALUES (?, 'PP-PERM', 'read', 'doc', ?, ?, 0)",
        (perm_id, now, now),
    )
    store.execute(
        "INSERT INTO role_permissions (role_id, permission_id, created_at)"
        " VALUES (?, ?, ?)",
        (role_id, perm_id, now),
    )
    store.execute(
        "INSERT INTO person_roles (id, person_id, role_id, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
        (new_id(), person_id, role_id, now, now),
    )
    assert store.count("person_positions", "person_id = ?", (person_id,)) == 1
    assert store.count("person_roles", "person_id = ?", (person_id,)) == 1


def test_project_assignment_task_workflow_approval_chain(store):
    now = utcnow_iso()
    person_id, project_id, role_id = new_id(), new_id(), new_id()
    store.execute(
        "INSERT INTO persons (id, code, full_name, status, created_at,"
        " updated_at, is_deleted) VALUES (?, 'CH-P', 'Chain', 'active', ?, ?, 0)",
        (person_id, now, now),
    )
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, 'CH-PR', 'Chain', 'active', ?, ?, 0)",
        (project_id, now, now),
    )
    store.execute(
        "INSERT INTO project_roles (id, code, name, authority_level,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, 'CH-RL', 'Member', 1, ?, ?, 0)",
        (role_id, now, now),
    )
    store.execute(
        "INSERT INTO project_assignments (id, project_id, person_id,"
        " project_role_id, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, 0)",
        (new_id(), project_id, person_id, role_id, now, now),
    )
    store.execute(
        "INSERT INTO tasks (id, project_id, assignee_person_id, title,"
        " status, priority, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 'Chain task', 'open', 'normal', ?, ?, 0)",
        (new_id(), project_id, person_id, now, now),
    )
    wf_id = new_id()
    store.execute(
        "INSERT INTO workflows (id, code, name, version, definition, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, 'CH-WF', 'Chain WF', 1, '{}', 'active', ?, ?, 0)",
        (wf_id, now, now),
    )
    inst_id = new_id()
    store.execute(
        "INSERT INTO workflow_instances (id, workflow_id, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, 'running', ?, ?, 0)",
        (inst_id, wf_id, now, now),
    )
    store.execute(
        "INSERT INTO approvals (id, workflow_instance_id, requester_person_id,"
        " action, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 'approve', 'pending', ?, ?, 0)",
        (new_id(), inst_id, person_id, now, now),
    )
    assert store.count("tasks", "project_id = ?", (project_id,)) == 1
    assert store.count("approvals", "workflow_instance_id = ?", (inst_id,)) == 1


def test_seed_dak_integrity(store):
    first = seed_dak(store)
    assert first["companies"] >= 1
    codes = {r["code"] for r in store.query_all("SELECT code FROM departments")}
    assert "BGD" in codes
    for code, _ in DEPARTMENTS:
        assert code in codes, f"missing department {code}"
    dept_count = store.count("departments", "is_deleted = 0")
    assert dept_count == 8  # BGD + 7 functional
    pos_count = store.count("positions", "is_deleted = 0")
    assert pos_count >= 2 + 7 * 3  # board + 3 templates per dept
    # no real personal names seeded
    assert store.count("persons", "is_deleted = 0") == 0
    # idempotent rerun
    second = seed_dak(store)
    assert second == first
    assert _ids(store, "departments", "TCHC")
    assert _ids(store, "positions", "DAK-BGD-GD")
