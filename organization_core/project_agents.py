"""LONGTHINK ORGANIZATION CORE — Phase 06 project organization & Project Agent.

Horizontal layer: Project -> Assignments (matrix with departments) ->
Tasks / Milestones / Risks / Issues / Decisions. Project roles are
configurable (catalog below + custom codes allowed).

The Project Agent is a coordinator (context/team/packages/tasks/milestones/
risks/issues/decisions/approvals/summary) — explicitly NOT a final approver:
this module never changes approval states.
"""

from __future__ import annotations

from organization_core.adapters import AdapterBundle
from organization_core.models import new_id, utcnow_iso
from organization_core.org_structure import get_project_team
from organization_core.store import OrganizationStore, decode_json, encode_json

# Configurable catalog: (code, name, authority_level). Custom codes accepted.
PROJECT_ROLE_CATALOG: tuple[tuple[str, str, int], ...] = (
    ("PROJECT_MANAGER", "Project Manager", 90),
    ("PROJECT_ENGINEER", "Project Engineer", 70),
    ("DISCIPLINE_LEAD", "Discipline Lead", 60),
    ("DOCUMENT_CONTROLLER", "Document Controller", 40),
    ("CONTRACT_SPECIALIST", "Contract Specialist", 50),
    ("QA_QC", "QA/QC", 50),
    ("HSE", "HSE", 50),
    ("FINANCE", "Finance", 40),
    ("PLANNING", "Planning", 40),
)

PROJECT_AGENT_RESPONSIBILITIES = (
    "project context", "team context", "work packages", "tasks",
    "milestones", "risks", "issues", "decisions", "pending approvals",
    "project summary",
)


def ensure_project_roles(
    store: OrganizationStore,
    extra: list[tuple[str, str, int]] | None = None,
) -> list[dict]:
    """Upsert the role catalog (+ optional custom roles). Idempotent."""
    now = utcnow_iso()
    roles = []
    for code, name, level in list(PROJECT_ROLE_CATALOG) + list(extra or []):
        row = store.query_one(
            "SELECT * FROM project_roles WHERE code = ?", (code,))
        if row is None:
            rid = new_id()
            store.execute(
                "INSERT INTO project_roles (id, code, name, authority_level,"
                " created_at, updated_at, is_deleted)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)",
                (rid, code, name, level, now, now),
            )
            row = store.query_one(
                "SELECT * FROM project_roles WHERE id = ?", (rid,))
        roles.append(dict(row))
    return roles


def create_project(store: OrganizationStore, code: str, name: str) -> dict:
    row = store.query_one("SELECT * FROM projects WHERE code = ?", (code,))
    if row:
        return dict(row)
    now = utcnow_iso()
    pid = new_id()
    store.execute(
        "INSERT INTO projects (id, code, name, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, 'active', ?, ?, 0)",
        (pid, code, name, now, now),
    )
    return dict(store.query_one("SELECT * FROM projects WHERE id = ?", (pid,)))


def assign_member(
    store: OrganizationStore,
    project_id: str,
    person_id: str,
    role_code: str | None = None,
) -> dict:
    role_id = None
    if role_code:
        row = store.query_one(
            "SELECT id FROM project_roles WHERE code = ?", (role_code,))
        if row is None:
            raise LookupError(f"Unknown project role: {role_code}")
        role_id = row["id"]
    now = utcnow_iso()
    aid = new_id()
    store.execute(
        "INSERT INTO project_assignments (id, project_id, person_id,"
        " project_role_id, status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, 0)",
        (aid, project_id, person_id, role_id, now, now),
    )
    return dict(store.query_one(
        "SELECT * FROM project_assignments WHERE id = ?", (aid,)))


def add_task(store: OrganizationStore, project_id: str, title: str,
             assignee_person_id: str | None = None) -> dict:
    now = utcnow_iso()
    tid = new_id()
    store.execute(
        "INSERT INTO tasks (id, project_id, assignee_person_id, title,"
        " status, priority, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'open', 'normal', ?, ?, 0)",
        (tid, project_id, assignee_person_id, title, now, now),
    )
    return dict(store.query_one("SELECT * FROM tasks WHERE id = ?", (tid,)))


def add_milestone(store: OrganizationStore, project_id: str, title: str,
                  due_at: str | None = None) -> dict:
    now = utcnow_iso()
    mid = new_id()
    store.execute(
        "INSERT INTO project_milestones (id, project_id, title, due_at,"
        " status, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'planned', ?, ?, 0)",
        (mid, project_id, title, due_at, now, now),
    )
    return dict(store.query_one(
        "SELECT * FROM project_milestones WHERE id = ?", (mid,)))


def add_risk(store: OrganizationStore, project_id: str, title: str,
             severity: str = "medium") -> dict:
    now = utcnow_iso()
    rid = new_id()
    store.execute(
        "INSERT INTO risks (id, project_id, title, severity, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'open', ?, ?, 0)",
        (rid, project_id, title, severity, now, now),
    )
    return dict(store.query_one("SELECT * FROM risks WHERE id = ?", (rid,)))


def add_issue(store: OrganizationStore, project_id: str, title: str) -> dict:
    now = utcnow_iso()
    iid = new_id()
    store.execute(
        "INSERT INTO issues (id, project_id, title, status, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, 'open', ?, ?, 0)",
        (iid, project_id, title, now, now),
    )
    return dict(store.query_one("SELECT * FROM issues WHERE id = ?", (iid,)))


def add_decision(store: OrganizationStore, project_id: str, title: str,
                 content: str = "") -> dict:
    now = utcnow_iso()
    did = new_id()
    store.execute(
        "INSERT INTO decisions (id, project_id, title, content, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'draft', ?, ?, 0)",
        (did, project_id, title, content, now, now),
    )
    return dict(store.query_one(
        "SELECT * FROM decisions WHERE id = ?", (did,)))


def ensure_project_agent(store: OrganizationStore, project_id: str) -> dict:
    project = store.query_one(
        "SELECT * FROM projects WHERE id = ? AND is_deleted = 0",
        (project_id,),
    )
    if project is None:
        raise LookupError(f"Project not found: {project_id}")
    config = {
        "agent_code": f"PROJECT_AGENT_{project['code']}",
        "project_id": project_id,
        "project_code": project["code"],
        "responsibilities": list(PROJECT_AGENT_RESPONSIBILITIES),
        "final_approver": False,
        "allowed_tools": ["project.read", "docs.search", "project.report"],
    }
    now = utcnow_iso()
    existing = store.query_one(
        "SELECT * FROM agents WHERE kind = 'project' AND ref_type = 'project'"
        " AND ref_id = ? AND is_deleted = 0",
        (project_id,),
    )
    if existing:
        store.execute(
            "UPDATE agents SET config = ?, status = 'active', updated_at = ?"
            " WHERE id = ?",
            (encode_json(config), now, existing["id"]),
        )
        row = store.query_one("SELECT * FROM agents WHERE id = ?",
                              (existing["id"],))
    else:
        aid = new_id()
        store.execute(
            "INSERT INTO agents (id, kind, name, ref_type, ref_id, config,"
            " status, created_at, updated_at, is_deleted)"
            " VALUES (?, 'project', ?, 'project', ?, ?, 'active', ?, ?, 0)",
            (aid, config["agent_code"], project_id, encode_json(config),
             now, now),
        )
        row = store.query_one("SELECT * FROM agents WHERE id = ?", (aid,))
    item = dict(row)
    item["config"] = decode_json(item.get("config"))
    return item


def _by_status(rows: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.get("status", "?")] = counts.get(row.get("status", "?"), 0) + 1
    return counts


def get_project_summary(store: OrganizationStore,
                        project_id: str) -> dict:
    """Coordinator view. Read-only: never mutates approvals or members."""
    project = store.query_one(
        "SELECT * FROM projects WHERE id = ? AND is_deleted = 0",
        (project_id,),
    )
    if project is None:
        raise LookupError(f"Project not found: {project_id}")
    team = get_project_team(store, project_id) or {"members": []}
    member_ids = [m["person_id"] for m in team["members"]]
    tasks = [dict(r) for r in store.query_all(
        "SELECT * FROM tasks WHERE project_id = ? AND is_deleted = 0",
        (project_id,))]
    milestones = [dict(r) for r in store.query_all(
        "SELECT * FROM project_milestones WHERE project_id = ?"
        " AND is_deleted = 0 ORDER BY due_at",
        (project_id,))]
    risks = [dict(r) for r in store.query_all(
        "SELECT * FROM risks WHERE project_id = ? AND is_deleted = 0",
        (project_id,))]
    issues = [dict(r) for r in store.query_all(
        "SELECT * FROM issues WHERE project_id = ? AND is_deleted = 0",
        (project_id,))]
    decisions = [dict(r) for r in store.query_all(
        "SELECT * FROM decisions WHERE project_id = ? AND is_deleted = 0",
        (project_id,))]
    approvals: list[dict] = []
    if member_ids:
        placeholders = ",".join("?" for _ in member_ids)
        approvals = [dict(r) for r in store.query_all(
            f"SELECT * FROM approvals WHERE status = 'pending'"
            f" AND is_deleted = 0 AND (requester_person_id IN"
            f" ({placeholders}) OR approver_person_id IN ({placeholders}))",
            tuple(member_ids) * 2,
        )]
    agent = ensure_project_agent(store, project_id)
    return {
        "project": dict(project),
        "agent": {"agent_code": agent["config"]["agent_code"],
                  "responsibilities": agent["config"]["responsibilities"],
                  "final_approver": False},
        "team_size": len(team["members"]),
        "members": team["members"],
        "tasks": {"total": len(tasks), "by_status": _by_status(tasks),
                  "items": tasks},
        "milestones": milestones,
        "risks": {"open": sum(1 for r in risks if r["status"] == "open"),
                  "items": risks},
        "issues": {"open": sum(1 for i in issues if i["status"] == "open"),
                   "items": issues},
        "decisions": decisions,
        "pending_approvals": approvals,
    }


def project_brief(store: OrganizationStore, project_id: str,
                  adapters: AdapterBundle | None = None) -> dict:
    """Narrative brief from the coordinator (mock intelligence)."""
    adapters = adapters or AdapterBundle.mocks()
    summary = get_project_summary(store, project_id)
    narrative = adapters.intelligence.ask(
        f"Summarize project {summary['project']['code']}",
        {"project": summary["project"]["code"],
         "team_size": summary["team_size"],
         "tasks": summary["tasks"]["total"]},
    )
    return {**summary, "brief": narrative["answer"],
            "backend": narrative["backend"]}
