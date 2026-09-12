"""LONGTHINK ORGANIZATION CORE — Phase 10 Enterprise Agent.

Company-level observe / analyze / recommend / prepare / route / coordinate.
High-impact actions (hire-dismiss, permission changes, finance approvals,
contract signing, org-structure changes, security-policy changes) are NEVER
autonomous: banned categories are always refused; any other execution needs
both an explicit allow policy AND Phase 02 authorization.
"""

from __future__ import annotations

from organization_core.adapters import AdapterBundle
from organization_core.auth import AuthContext, AuthorizationError, authorize
from organization_core.models import new_id, utcnow_iso
from organization_core.store import OrganizationStore, decode_json, encode_json

READ_VERBS = frozenset(
    {"observe", "analyze", "recommend", "prepare", "route", "coordinate"})

# Absolute bans: no policy can unlock these for the Enterprise Agent.
BANNED_ACTIONS: frozenset[tuple[str, str]] = frozenset({
    ("CREATE", "person"),       # hire
    ("DELETE", "person"),       # dismiss
    ("ASSIGN", "role"),         # change permissions (agent self-serve)
    ("ADMIN", "permission"),    # change permissions
    ("APPROVE", "payment"),     # finance approval requiring a human
    ("EXECUTE", "contract"),    # sign contract
    ("UPDATE", "org_authority"),  # org-structure / authority changes
    ("UPDATE", "department"),   # org-structure changes
    ("UPDATE", "security_policy"),  # security policy changes
})

EXECUTION_ALLOW_POLICY = "ENTERPRISE_EXECUTION_ALLOW"


def ensure_enterprise_agent(store: OrganizationStore) -> dict:
    config = {
        "agent_code": "ENTERPRISE_AGENT",
        "responsibilities": [
            "company overview", "department health", "project portfolio",
            "project status", "risk overview", "issue overview",
            "pending approvals", "resource overview", "executive brief",
            "cross-department coordination",
        ],
        "allowed_verbs": sorted(READ_VERBS),
        "banned_actions": sorted(f"{a}:{r}" for a, r in BANNED_ACTIONS),
        "final_approver": False,
    }
    now = utcnow_iso()
    existing = store.query_one(
        "SELECT * FROM agents WHERE kind = 'enterprise'"
        " AND name = 'ENTERPRISE_AGENT' AND is_deleted = 0")
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
            "INSERT INTO agents (id, kind, name, config, status, created_at,"
            " updated_at, is_deleted) VALUES (?, 'enterprise',"
            " 'ENTERPRISE_AGENT', ?, 'active', ?, ?, 0)",
            (aid, encode_json(config), now, now),
        )
        row = store.query_one("SELECT * FROM agents WHERE id = ?", (aid,))
    item = dict(row)
    item["config"] = decode_json(item.get("config"))
    return item


def _actor_scope(store: OrganizationStore, actor_person_id: str) -> dict:
    person = store.query_one(
        "SELECT id FROM persons WHERE id = ? AND status = 'active'"
        " AND is_deleted = 0",
        (actor_person_id,),
    )
    if person is None:
        raise AuthorizationError("unknown or inactive actor")
    roles = {r["code"] for r in store.query_all(
        "SELECT r.code AS code FROM person_roles pr "
        "JOIN roles r ON r.id = pr.role_id AND r.is_deleted = 0 "
        "WHERE pr.person_id = ? AND pr.is_deleted = 0", (actor_person_id,))}
    perms = {(r["action"], r["resource"]) for r in store.query_all(
        "SELECT p.action AS action, p.resource AS resource"
        " FROM person_roles pr JOIN roles r ON r.id = pr.role_id"
        " AND r.is_deleted = 0 JOIN role_permissions rp ON rp.role_id = r.id"
        " JOIN permissions p ON p.id = rp.permission_id AND p.is_deleted = 0"
        " WHERE pr.person_id = ? AND pr.is_deleted = 0", (actor_person_id,))}
    is_admin = "ADMIN" in roles or ("ADMIN", "*") in perms
    departments = {r["department_id"] for r in store.query_all(
        "SELECT pos.department_id AS department_id FROM person_positions pp "
        "JOIN positions pos ON pos.id = pp.position_id AND pos.is_deleted = 0 "
        "WHERE pp.person_id = ? AND pp.is_deleted = 0", (actor_person_id,))}
    departments.discard(None)
    projects = {r["project_id"] for r in store.query_all(
        "SELECT project_id FROM project_assignments WHERE person_id = ?"
        " AND status = 'active' AND is_deleted = 0", (actor_person_id,))}
    return {"is_admin": is_admin, "departments": departments,
            "projects": projects, "person_id": actor_person_id}


def _redact_members(members: list[dict], is_admin: bool) -> list[dict]:
    if is_admin:
        return members
    return [{k: v for k, v in m.items() if k != "full_name"}
            for m in members]


def department_health(store: OrganizationStore,
                      actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = store.query_all(
        "SELECT * FROM departments WHERE is_deleted = 0 ORDER BY code")
    health = []
    for row in rows:
        if not scope["is_admin"] and row["id"] not in scope["departments"]:
            continue
        members = [dict(m) for m in store.query_all(
            "SELECT ps.id AS person_id, ps.code AS person_code,"
            " ps.full_name AS full_name, pos.code AS position_code"
            " FROM person_positions pp "
            "JOIN persons ps ON ps.id = pp.person_id AND ps.is_deleted = 0 "
            "JOIN positions pos ON pos.id = pp.position_id"
            " WHERE pos.department_id = ? AND pp.is_deleted = 0",
            (row["id"],))]
        health.append({
            "code": row["code"], "name": row["name"], "status": row["status"],
            "teams": store.count("teams", "department_id = ?"
                                 " AND is_deleted = 0", (row["id"],)),
            "positions": store.count("positions", "department_id = ?"
                                     " AND is_deleted = 0", (row["id"],)),
            "members": _redact_members(members, scope["is_admin"]),
            "member_count": len(members),
            "open_tasks": store.count("tasks", "department_id = ?"
                                      " AND status NOT IN ('done',"
                                      " 'cancelled') AND is_deleted = 0",
                                      (row["id"],)),
        })
    return {"departments": health}


def project_portfolio(store: OrganizationStore,
                      actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = store.query_all(
        "SELECT * FROM projects WHERE is_deleted = 0 ORDER BY code")
    portfolio = []
    for row in rows:
        if not scope["is_admin"] and row["id"] not in scope["projects"]:
            continue
        team = store.count("project_assignments", "project_id = ?"
                           " AND is_deleted = 0", (row["id"],))
        tasks = store.count("tasks", "project_id = ? AND is_deleted = 0",
                            (row["id"],))
        open_tasks = store.count("tasks", "project_id = ? AND status NOT IN"
                                 " ('done', 'cancelled') AND is_deleted = 0",
                                 (row["id"],))
        portfolio.append({
            "code": row["code"], "name": row["name"], "status": row["status"],
            "team_size": team, "tasks_total": tasks,
            "tasks_open": open_tasks,
            "milestones": store.count("project_milestones",
                                      "project_id = ? AND is_deleted = 0",
                                      (row["id"],)),
            "risks_open": store.count("risks", "project_id = ?"
                                      " AND status = 'open'"
                                      " AND is_deleted = 0", (row["id"],)),
            "issues_open": store.count("issues", "project_id = ?"
                                       " AND status = 'open'"
                                       " AND is_deleted = 0", (row["id"],)),
        })
    return {"projects": portfolio}


def risk_overview(store: OrganizationStore, actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = [dict(r) for r in store.query_all(
        "SELECT r.*, p.code AS project_code FROM risks r "
        "LEFT JOIN projects p ON p.id = r.project_id "
        "WHERE r.is_deleted = 0 ORDER BY r.severity")]
    if not scope["is_admin"]:
        rows = [r for r in rows if r["project_id"] in scope["projects"]]
    return {"risks": rows}


def issue_overview(store: OrganizationStore, actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = [dict(r) for r in store.query_all(
        "SELECT i.*, p.code AS project_code FROM issues i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE i.is_deleted = 0")]
    if not scope["is_admin"]:
        rows = [r for r in rows if r["project_id"] in scope["projects"]]
    return {"issues": rows}


def pending_approvals(store: OrganizationStore,
                      actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = [dict(r) for r in store.query_all(
        "SELECT * FROM approvals WHERE status = 'pending'"
        " AND is_deleted = 0 ORDER BY created_at")]
    if not scope["is_admin"]:
        rows = [r for r in rows
                if r["requester_person_id"] == actor_person_id
                or r["approver_person_id"] == actor_person_id]
        for row in rows:
            row.pop("reason", None)  # sensitive-data filtering
    return {"approvals": rows}


def resource_overview(store: OrganizationStore,
                      actor_person_id: str) -> dict:
    scope = _actor_scope(store, actor_person_id)
    rows = store.query_all(
        "SELECT * FROM departments WHERE is_deleted = 0 ORDER BY code")
    resources = []
    for row in rows:
        if not scope["is_admin"] and row["id"] not in scope["departments"]:
            continue
        baseline = store.query_one(
            "SELECT COALESCE(SUM(headcount_baseline), 0) AS n FROM positions"
            " WHERE department_id = ? AND is_deleted = 0", (row["id"],))
        assigned = store.query_one(
            "SELECT COUNT(DISTINCT pp.person_id) AS n FROM person_positions pp"
            " JOIN positions pos ON pos.id = pp.position_id"
            " WHERE pos.department_id = ? AND pp.is_deleted = 0", (row["id"],))
        resources.append({
            "department": row["code"], "headcount_baseline": baseline["n"],
            "assigned": assigned["n"],
        })
    total_base = sum(r["headcount_baseline"] for r in resources)
    total_assigned = sum(r["assigned"] for r in resources)
    return {"departments": resources, "total_baseline": total_base,
            "total_assigned": total_assigned}


def company_overview(store: OrganizationStore,
                     actor_person_id: str) -> dict:
    ensure_enterprise_agent(store)
    scope = _actor_scope(store, actor_person_id)
    company = store.query_one(
        "SELECT * FROM companies WHERE code = 'DAK' AND is_deleted = 0")
    health = department_health(store, actor_person_id)["departments"]
    portfolio = project_portfolio(store, actor_person_id)["projects"]
    return {
        "company": dict(company) if company else None,
        "is_admin_view": scope["is_admin"],
        "department_count": len(health),
        "project_count": len(portfolio),
        "open_tasks": sum(1 for _ in store.query_all(
            "SELECT id FROM tasks WHERE status NOT IN ('done', 'cancelled')"
            " AND is_deleted = 0")),
        "pending_approvals": len(
            pending_approvals(store, actor_person_id)["approvals"]),
    }


def executive_brief(store: OrganizationStore, actor_person_id: str,
                    adapters: AdapterBundle | None = None) -> dict:
    adapters = adapters or AdapterBundle.mocks()
    overview = company_overview(store, actor_person_id)
    risks = risk_overview(store, actor_person_id)["risks"]
    top_risks = [r["title"] for r in risks[:5]]
    narrative = adapters.intelligence.ask(
        f"Executive brief for {overview['company']['code']}: "
        f"{overview['project_count']} projects, "
        f"{overview['pending_approvals']} pending approvals.",
        {"actor_id": actor_person_id})
    _audit(store, actor_person_id, "enterprise.brief",
           "Company brief generated")
    from organization_core import governance as gov_module

    return {**overview, "top_risks": top_risks,
            "brief": gov_module.redact_secrets(narrative["answer"]),
            "backend": narrative["backend"]}


def enterprise_act(store: OrganizationStore, actor_person_id: str,
                   verb: str, action: str = "", resource: str = "",
                   context: dict | None = None) -> dict:
    """Guarded enterprise action. Read verbs always OK; execution gated."""
    _actor_scope(store, actor_person_id)  # validates actor
    context = context or {}
    if verb in READ_VERBS:
        _audit(store, actor_person_id, f"enterprise.{verb}",
               f"{action}:{resource}")
        return {"allowed": True, "verb": verb, "note": "read-only verb"}
    if (action, resource) in BANNED_ACTIONS:
        _audit(store, actor_person_id, "enterprise.refused",
               f"BANNED {action}:{resource}")
        return {"allowed": False, "verb": verb,
                "reason": f"high-impact action {action}:{resource}"
                          " is never autonomous"}
    if verb != "execute":
        return {"allowed": False, "verb": verb, "reason": "unknown verb"}
    policy = store.query_one(
        "SELECT id FROM policies WHERE code = ? AND effect = 'allow'"
        " AND status = 'active' AND is_deleted = 0",
        (EXECUTION_ALLOW_POLICY,))
    if policy is None:
        _audit(store, actor_person_id, "enterprise.refused",
               "no execution policy")
        return {"allowed": False, "verb": verb,
                "reason": "no explicit execution policy"}
    decision = authorize(store, actor_person_id=actor_person_id,
                         action=action or "EXECUTE",
                         resource=resource or "task",
                         ctx=AuthContext(
                             project_id=context.get("project_id")))
    _audit(store, actor_person_id, "enterprise.execute",
           f"{action}:{resource} -> {decision.allow}")
    return {"allowed": decision.allow, "verb": verb,
            "reason": decision.reason}


def _audit(store: OrganizationStore, actor: str, action: str,
           note: str) -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, ?, 'enterprise_agent', NULL, ?, ?)",
        (new_id(), actor, action, encode_json({"note": note}), utcnow_iso()),
    )
