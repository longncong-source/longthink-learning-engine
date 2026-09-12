"""LONGTHINK ORGANIZATION CORE — Phase 03 organization structure service.

Dynamic, time-variable structure: every lookup accepts ``at`` (ISO8601).
``at=None`` means "current". History is derived from effective_from/to +
status + org_versions — never a single fixed chart.

Matrix model: one person may sit in a department, hold several positions,
join many projects with different project roles — authority always depends
on role/context (Phase 02 authorize).
"""

from __future__ import annotations

from organization_core.models import utcnow_iso
from organization_core.store import OrganizationStore, decode_json


def _at(at: str | None) -> str:
    return at or utcnow_iso()


def _window_ok(row, at: str) -> bool:
    keys = set(row.keys())
    frm = row["effective_from"] if "effective_from" in keys else None
    to = row["effective_to"] if "effective_to" in keys else None
    if frm and at < str(frm):
        return False
    return not (to and at > str(to))


def _row_dict(row) -> dict:
    data = dict(row)
    for key in ("authority_scope", "scope", "rules", "detail", "config",
                "definition", "metadata", "context"):
        if key in data and isinstance(data[key], str):
            data[key] = decode_json(data[key])
    return data


def current_version(store: OrganizationStore, at: str | None = None) -> dict | None:
    moment = _at(at)
    rows = store.query_all(
        "SELECT * FROM org_versions WHERE status = 'active'"
        " AND is_deleted = 0 ORDER BY version DESC"
    )
    for row in rows:
        if _window_ok(row, moment):
            return _row_dict(row)
    return None


def list_versions(store: OrganizationStore) -> list[dict]:
    rows = store.query_all(
        "SELECT * FROM org_versions WHERE is_deleted = 0 ORDER BY version"
    )
    return [_row_dict(r) for r in rows]


def get_organization(store: OrganizationStore, at: str | None = None) -> dict:
    moment = _at(at)
    company = store.query_one(
        "SELECT * FROM companies WHERE code = 'DAK' AND is_deleted = 0"
    )
    departments = list_departments(store, at=moment)
    tree = []
    for dept in departments:
        teams = store.query_all(
            "SELECT * FROM teams WHERE department_id = ? AND is_deleted = 0"
            " ORDER BY code",
            (dept["id"],),
        )
        teams = [t for t in (_row_dict(t) for t in teams)
                 if _window_ok(t, moment)]
        tree.append({
            **dept,
            "teams": teams,
            "position_count": store.count(
                "positions", "department_id = ? AND is_deleted = 0",
                (dept["id"],),
            ),
        })
    return {
        "company": _row_dict(company) if company else None,
        "version": current_version(store, at=moment),
        "departments": tree,
    }


def list_departments(
    store: OrganizationStore,
    status: str | None = None,
    at: str | None = None,
) -> list[dict]:
    moment = _at(at)
    sql = "SELECT * FROM departments WHERE is_deleted = 0"
    params: tuple = ()
    if status is not None:
        sql += " AND status = ?"
        params = (status,)
    sql += " ORDER BY code"
    return [_row_dict(r) for r in store.query_all(sql, params)
            if _window_ok(_row_dict(r), moment)]


def get_department(
    store: OrganizationStore, dept_id: str, at: str | None = None
) -> dict | None:
    moment = _at(at)
    row = store.query_one(
        "SELECT * FROM departments WHERE id = ? AND is_deleted = 0", (dept_id,)
    )
    if row is None:
        return None
    dept = _row_dict(row)
    teams = [_row_dict(t) for t in store.query_all(
        "SELECT * FROM teams WHERE department_id = ? AND is_deleted = 0"
        " ORDER BY code", (dept_id,))]
    teams = [t for t in teams if _window_ok(t, moment)]
    positions = [_row_dict(p) for p in store.query_all(
        "SELECT * FROM positions WHERE department_id = ? AND is_deleted = 0"
        " ORDER BY code", (dept_id,))]
    positions = [p for p in positions if _window_ok(p, moment)]
    return {**dept, "teams": teams, "positions": positions}


def get_person(store: OrganizationStore, person_id: str) -> dict | None:
    row = store.query_one(
        "SELECT * FROM persons WHERE id = ? AND is_deleted = 0", (person_id,)
    )
    if row is None:
        return None
    person = _row_dict(row)
    positions = [_row_dict(r) for r in store.query_all(
        "SELECT pp.*, pos.code AS position_code, pos.title AS position_title,"
        " pos.department_id AS department_id FROM person_positions pp "
        "JOIN positions pos ON pos.id = pp.position_id AND pos.is_deleted = 0 "
        "WHERE pp.person_id = ? AND pp.is_deleted = 0", (person_id,))]
    roles = [_row_dict(r) for r in store.query_all(
        "SELECT pr.*, r.code AS role_code, r.name AS role_name"
        " FROM person_roles pr JOIN roles r ON r.id = pr.role_id"
        " AND r.is_deleted = 0 WHERE pr.person_id = ? AND pr.is_deleted = 0",
        (person_id,))]
    return {**person, "positions": positions, "roles": roles}


def get_person_context(
    store: OrganizationStore, person_id: str, at: str | None = None
) -> dict | None:
    """Full organization context for a person (feeds Phase 04 assistant)."""
    moment = _at(at)
    person = get_person(store, person_id)
    if person is None:
        return None
    dept_ids = {p["department_id"] for p in person["positions"]
                if p.get("department_id")}
    departments = []
    for did in sorted(dept_ids):
        row = store.query_one(
            "SELECT * FROM departments WHERE id = ? AND is_deleted = 0", (did,)
        )
        if row:
            departments.append(_row_dict(row))
    company = store.query_one(
        "SELECT * FROM companies WHERE code = 'DAK' AND is_deleted = 0"
    )
    projects = get_person_projects(store, person_id, at=moment)
    delegations = [_row_dict(r) for r in store.query_all(
        "SELECT * FROM delegations WHERE (from_person_id = ?"
        " OR to_person_id = ?) AND status = 'active' AND is_deleted = 0",
        (person_id, person_id))]
    delegations = [d for d in delegations if _window_ok(d, moment)]
    assistants = [_row_dict(r) for r in store.query_all(
        "SELECT * FROM assistants WHERE owner_person_id = ?"
        " AND is_deleted = 0", (person_id,))]
    return {
        "person": {k: v for k, v in person.items()
                   if k not in ("positions", "roles")},
        "company": _row_dict(company) if company else None,
        "version": current_version(store, at=moment),
        "departments": departments,
        "positions": person["positions"],
        "roles": [r["role_code"] for r in person["roles"]],
        "projects": projects,
        "delegations": delegations,
        "assistants": assistants,
    }


def get_person_projects(
    store: OrganizationStore, person_id: str, at: str | None = None
) -> list[dict]:
    moment = _at(at)
    rows = store.query_all(
        "SELECT pa.*, p.code AS project_code, p.name AS project_name,"
        " p.status AS project_status, pr.code AS project_role_code,"
        " pr.name AS project_role_name FROM project_assignments pa "
        "JOIN projects p ON p.id = pa.project_id AND p.is_deleted = 0 "
        "LEFT JOIN project_roles pr ON pr.id = pa.project_role_id "
        "WHERE pa.person_id = ? AND pa.is_deleted = 0 ORDER BY p.code",
        (person_id,),
    )
    return [_row_dict(r) for r in rows if _window_ok(_row_dict(r), moment)]


def get_project_team(
    store: OrganizationStore, project_id: str, at: str | None = None
) -> dict | None:
    moment = _at(at)
    project = store.query_one(
        "SELECT * FROM projects WHERE id = ? AND is_deleted = 0", (project_id,)
    )
    if project is None:
        return None
    rows = store.query_all(
        "SELECT pa.*, ps.code AS person_code, ps.full_name AS person_name,"
        " pr.code AS project_role_code, pr.name AS project_role_name"
        " FROM project_assignments pa "
        "JOIN persons ps ON ps.id = pa.person_id AND ps.is_deleted = 0 "
        "LEFT JOIN project_roles pr ON pr.id = pa.project_role_id "
        "WHERE pa.project_id = ? AND pa.is_deleted = 0 ORDER BY ps.code",
        (project_id,),
    )
    members = []
    for row in rows:
        item = _row_dict(row)
        if not _window_ok(item, moment):
            continue
        depts = [_row_dict(d) for d in store.query_all(
            "SELECT d.* FROM person_positions pp "
            "JOIN positions pos ON pos.id = pp.position_id"
            " AND pos.is_deleted = 0 "
            "JOIN departments d ON d.id = pos.department_id"
            " AND d.is_deleted = 0 "
            "WHERE pp.person_id = ? AND pp.is_deleted = 0",
            (item["person_id"],))]
        item["departments"] = depts
        members.append(item)
    return {"project": _row_dict(project), "members": members}
