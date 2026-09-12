"""LONGTHINK ORGANIZATION CORE — Phase 02 identity, RBAC, ABAC & authority.

Authority model::

    Human authority -> Role / Position -> Permission -> Context -> Policy decision

Rules enforced here:
- deny by default, least privilege
- every decision is audited (audit_events)
- agents can never grant permissions/roles (no self-granting)
- grant operations require an authorized human (ASSIGN/ADMIN)
- cross-company and cross-project access denied unless explicitly allowed
- effective-date windows enforced for roles, assignments and delegations

No dependency on KNOWLEDGE / INTELLIGENCE CORE internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from organization_core.models import new_id, utcnow_iso
from organization_core.observability import inc as obs_inc
from organization_core.store import OrganizationStore, decode_json, encode_json

ACTIONS = frozenset(
    {
        "READ",
        "CREATE",
        "UPDATE",
        "DELETE",
        "ASSIGN",
        "APPROVE",
        "REJECT",
        "EXECUTE",
        "EXPORT",
        "ADMIN",
    }
)

#: Actions gated by require_approval policies (consequence-bearing actions).
APPROVAL_GATED = frozenset({"APPROVE", "EXECUTE", "DELETE", "EXPORT", "ADMIN"})

ADMIN_ROLE_CODE = "ADMIN"
ADMIN_OVERRIDE_POLICY = "ADMIN_OVERRIDE"


@dataclass(slots=True)
class AuthContext:
    """ABAC context for one authorization check."""

    department_id: str | None = None
    project_id: str | None = None
    company_id: str | None = None
    at: str | None = None  # ISO8601 instant; defaults to now
    approval_granted: bool = False
    actor_type: str = "human"  # human | agent


@dataclass(slots=True)
class Decision:
    allow: bool
    reason: str
    via: str = ""  # role:<code> | delegation:<id> | policy:<code> | none
    context: dict = field(default_factory=dict)


class AuthorizationError(PermissionError):
    """Raised by grant helpers when the authorizer lacks authority."""


# --- internal resolvers ----------------------------------------------------


def _now(at: str | None) -> str:
    return at or utcnow_iso()


def _in_window(row, at: str) -> bool:
    keys = set(row.keys())
    frm = row["effective_from"] if "effective_from" in keys else None
    to = row["effective_to"] if "effective_to" in keys else None
    if frm and at < str(frm):
        return False
    return not (to and at > str(to))


def _person(store: OrganizationStore, person_id: str):
    return store.query_one(
        "SELECT * FROM persons WHERE id = ? AND is_deleted = 0", (person_id,)
    )


def _role_permissions(store: OrganizationStore, person_id: str, at: str) -> dict:
    """(action, resource) -> role code for active, in-window person_roles."""
    rows = store.query_all(
        "SELECT pr.*, r.code AS role_code, p.action AS action,"
        " p.resource AS resource FROM person_roles pr "
        "JOIN roles r ON r.id = pr.role_id AND r.is_deleted = 0 "
        "JOIN role_permissions rp ON rp.role_id = r.id "
        "JOIN permissions p ON p.id = rp.permission_id AND p.is_deleted = 0 "
        "WHERE pr.person_id = ? AND pr.is_deleted = 0",
        (person_id,),
    )
    perms: dict[tuple[str, str], str] = {}
    for row in rows:
        if _in_window(row, at):
            perms[(row["action"], row["resource"])] = row["role_code"]
    return perms


def _person_departments(store: OrganizationStore, person_id: str, at: str) -> set[str]:
    rows = store.query_all(
        "SELECT pp.*, pos.department_id AS department_id FROM person_positions pp "
        "JOIN positions pos ON pos.id = pp.position_id AND pos.is_deleted = 0 "
        "WHERE pp.person_id = ? AND pp.is_deleted = 0",
        (person_id,),
    )
    return {
        r["department_id"]
        for r in rows
        if r["department_id"] and _in_window(r, at)
    }


def _person_projects(store: OrganizationStore, person_id: str, at: str) -> set[str]:
    rows = store.query_all(
        "SELECT * FROM project_assignments WHERE person_id = ?"
        " AND status = 'active' AND is_deleted = 0",
        (person_id,),
    )
    return {r["project_id"] for r in rows if _in_window(r, at)}


def _person_company(store: OrganizationStore, person_id: str, at: str) -> str | None:
    depts = _person_departments(store, person_id, at)
    if not depts:
        return None
    row = store.query_one(
        "SELECT company_id FROM departments WHERE id = ?",
        (next(iter(sorted(depts))),),
    )
    return row["company_id"] if row else None


def _valid_delegations(
    store: OrganizationStore, to_person_id: str, at: str
) -> list:
    rows = store.query_all(
        "SELECT * FROM delegations WHERE to_person_id = ?"
        " AND status = 'active' AND is_deleted = 0",
        (to_person_id,),
    )
    return [r for r in rows if _in_window(r, at)]


def _scope_covers(scope: dict, action: str, resource: str, ctx: AuthContext) -> bool:
    actions = scope.get("actions", [])
    resources = scope.get("resources", [])
    if actions != "*" and action not in actions:
        return False
    if resources != "*" and resource not in resources:
        return False
    if scope.get("project_id") and scope["project_id"] != ctx.project_id:
        return False
    return not (
        scope.get("department_id") and scope["department_id"] != ctx.department_id
    )


def _active_policies(store: OrganizationStore, at: str) -> list:
    rows = store.query_all(
        "SELECT * FROM policies WHERE status = 'active' AND is_deleted = 0"
    )
    return [r for r in rows if _in_window(r, at)]


def _policy_matches(rules: dict, action: str, resource: str) -> bool:
    actions = rules.get("actions", [])
    resources = rules.get("resources", [])
    if actions and actions != "*" and action not in actions:
        return False
    return not (resources and resources != "*" and resource not in resources)


def _audit_decision(
    store: OrganizationStore,
    ctx: AuthContext,
    actor_id: str,
    action: str,
    resource: str,
    decision: Decision,
) -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, ?, ?, ?, 'authorization', NULL, ?, ?)",
        (
            new_id(),
            ctx.actor_type,
            actor_id,
            f"authorize:{action}:{resource}",
            encode_json(
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "via": decision.via,
                    "department_id": ctx.department_id,
                    "project_id": ctx.project_id,
                    "company_id": ctx.company_id,
                }
            ),
            utcnow_iso(),
        ),
    )


# --- public API ------------------------------------------------------------


def authorize(
    store: OrganizationStore,
    *,
    actor_person_id: str,
    action: str,
    resource: str,
    ctx: AuthContext | None = None,
) -> Decision:
    """Evaluate actor x action x resource x context -> ALLOW/DENY (audited)."""
    ctx = ctx or AuthContext()
    at = _now(ctx.at)

    def deny(reason: str, via: str = "none") -> Decision:
        decision = Decision(allow=False, reason=reason, via=via)
        obs_inc("org_authorization_denied_total")
        _audit_decision(store, ctx, actor_person_id, action, resource, decision)
        return decision

    def allow(reason: str, via: str) -> Decision:
        decision = Decision(allow=True, reason=reason, via=via)
        _audit_decision(store, ctx, actor_person_id, action, resource, decision)
        return decision

    if action not in ACTIONS:
        return deny(f"unknown action {action!r}")

    actor = _person(store, actor_person_id)
    if actor is None:
        return deny("unknown actor")
    if actor["status"] != "active":
        return deny("actor not active")

    policies = _active_policies(store, at)
    for policy in policies:
        if policy["effect"] != "deny":
            continue
        if _policy_matches(decode_json(policy["rules"]), action, resource):
            return deny(
                f"deny policy {policy['code']}", via=f"policy:{policy['code']}"
            )

    perms = _role_permissions(store, actor_person_id, at)
    is_admin = (ADMIN_ROLE_CODE in set(perms.values())) or (
        ("ADMIN", "*") in perms
    )
    if is_admin:
        override = next(
            (
                p
                for p in policies
                if p["code"] == ADMIN_OVERRIDE_POLICY and p["effect"] == "allow"
            ),
            None,
        )
        if override is not None:
            return allow("admin override policy", via="policy:ADMIN_OVERRIDE")

    if ctx.company_id is not None:
        home = _person_company(store, actor_person_id, at)
        if home is not None and home != ctx.company_id:
            return deny("cross-company access denied")

    if ctx.department_id is not None and not is_admin:
        depts = _person_departments(store, actor_person_id, at)
        delegated = any(
            _scope_covers(decode_json(d["scope"]), action, resource, ctx)
            for d in _valid_delegations(store, actor_person_id, at)
        )
        if ctx.department_id not in depts and not delegated:
            return deny("department scope denied")

    if ctx.project_id is not None and not is_admin:
        projects = _person_projects(store, actor_person_id, at)
        delegated = any(
            _scope_covers(decode_json(d["scope"]), action, resource, ctx)
            for d in _valid_delegations(store, actor_person_id, at)
        )
        if ctx.project_id not in projects and not delegated:
            return deny("project scope denied")

    via_role = perms.get((action, resource)) or perms.get((action, "*"))
    if via_role is None:
        for delegation in _valid_delegations(store, actor_person_id, at):
            if _scope_covers(decode_json(delegation["scope"]), action, resource, ctx):
                via_role = f"delegation:{delegation['id']}"
                break
    if via_role is None:
        return deny("deny by default: no permission")
    via = via_role if via_role.startswith("delegation:") else f"role:{via_role}"

    if action in APPROVAL_GATED and not is_admin:
        gated = any(
            p["effect"] == "require_approval"
            and _policy_matches(decode_json(p["rules"]), action, resource)
            for p in policies
        )
        if gated and not ctx.approval_granted:
            return deny("policy requires approval", via=via)

    return allow("permission granted", via=via)


# --- managed mutations (escalation-safe) -----------------------------------


def _require_human_authorizer(
    store: OrganizationStore, authorized_by: str, actor_type: str
) -> None:
    if actor_type == "agent":
        raise AuthorizationError("agents cannot grant authority")
    decision = authorize(
        store,
        actor_person_id=authorized_by,
        action="ASSIGN",
        resource="role",
    )
    if not decision.allow:
        raise AuthorizationError(f"authorizer lacks ASSIGN: {decision.reason}")


def ensure_permission(
    store: OrganizationStore, action: str, resource: str
) -> str:
    code = f"{action}:{resource}"
    row = store.query_one("SELECT id FROM permissions WHERE code = ?", (code,))
    if row:
        return row["id"]
    now = utcnow_iso()
    pid = new_id()
    store.execute(
        "INSERT INTO permissions (id, code, action, resource, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, 0)",
        (pid, code, action, resource, now, now),
    )
    return pid


def ensure_role(store: OrganizationStore, code: str, name: str) -> str:
    row = store.query_one("SELECT id FROM roles WHERE code = ?", (code,))
    if row:
        return row["id"]
    now = utcnow_iso()
    rid = new_id()
    store.execute(
        "INSERT INTO roles (id, code, name, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
        (rid, code, name, now, now),
    )
    return rid


def grant_permission_to_role(
    store: OrganizationStore, role_code: str, action: str, resource: str
) -> None:
    rid = ensure_role(store, role_code, role_code)
    pid = ensure_permission(store, action, resource)
    exists = store.query_one(
        "SELECT 1 AS ok FROM role_permissions WHERE role_id = ?"
        " AND permission_id = ?",
        (rid, pid),
    )
    if not exists:
        store.execute(
            "INSERT INTO role_permissions (role_id, permission_id, created_at)"
            " VALUES (?, ?, ?)",
            (rid, pid, utcnow_iso()),
        )


def grant_role(
    store: OrganizationStore,
    *,
    authorized_by: str,
    person_id: str,
    role_code: str,
    actor_type: str = "human",
) -> Decision:
    """Grant a role after authorizer check; blocks agent/self-admin grants."""
    if actor_type == "agent":
        decision = Decision(False, "agents cannot grant authority", via="none")
        _audit_decision(
            store, AuthContext(actor_type=actor_type), authorized_by,
            "ASSIGN", "role", decision,
        )
        raise AuthorizationError("agents cannot grant authority")
    if authorized_by == person_id and role_code == ADMIN_ROLE_CODE:
        decision = Decision(False, "self-grant of ADMIN denied", via="none")
        _audit_decision(
            store, AuthContext(actor_type=actor_type), authorized_by,
            "ASSIGN", "role", decision,
        )
        raise AuthorizationError("self-grant of ADMIN denied")
    _require_human_authorizer(store, authorized_by, actor_type)
    if role_code == ADMIN_ROLE_CODE:
        admin_check = authorize(
            store, actor_person_id=authorized_by, action="ADMIN", resource="*"
        )
        if not admin_check.allow:
            raise AuthorizationError("granting ADMIN requires ADMIN authority")
    rid = ensure_role(store, role_code, role_code)
    now = utcnow_iso()
    exists = store.query_one(
        "SELECT id FROM person_roles WHERE person_id = ? AND role_id = ?"
        " AND is_deleted = 0",
        (person_id, rid),
    )
    if not exists:
        store.execute(
            "INSERT INTO person_roles (id, person_id, role_id, created_at,"
            " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, 0)",
            (new_id(), person_id, rid, now, now),
        )
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, ?, ?, 'role.grant', 'person', ?, ?, ?)",
        (
            new_id(),
            actor_type,
            authorized_by,
            person_id,
            encode_json({"role": role_code}),
            utcnow_iso(),
        ),
    )
    return Decision(True, "role granted", via=f"role:{role_code}")


def create_delegation(
    store: OrganizationStore,
    *,
    authorized_by: str,
    from_person_id: str,
    to_person_id: str,
    scope: dict,
    effective_from: str | None = None,
    effective_to: str | None = None,
    reason: str | None = None,
    actor_type: str = "human",
) -> str:
    """Create a delegation; only the delegator (or ASSIGN holder) may create it."""
    if actor_type == "agent":
        raise AuthorizationError("agents cannot create delegations")
    if authorized_by != from_person_id:
        _require_human_authorizer(store, authorized_by, actor_type)
    now = utcnow_iso()
    did = new_id()
    store.execute(
        "INSERT INTO delegations (id, from_person_id, to_person_id, scope,"
        " status, effective_from, effective_to, policy_ref, reason,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'active', ?, ?, NULL, ?, ?, ?, 0)",
        (
            did,
            from_person_id,
            to_person_id,
            encode_json(scope),
            effective_from or now,
            effective_to,
            reason,
            now,
            now,
        ),
    )
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, ?, ?, 'delegation.create', 'delegation', ?, ?, ?)",
        (
            new_id(),
            actor_type,
            authorized_by,
            did,
            encode_json({"from": from_person_id, "to": to_person_id}),
            utcnow_iso(),
        ),
    )
    return did


def _snapshot_policy_version(store: OrganizationStore, policy_id: str) -> None:
    """Append-only history row for the policy's current version (Phase 11)."""
    row = store.query_one("SELECT * FROM policies WHERE id = ?", (policy_id,))
    if row is None:
        return
    try:
        keys = set(row.keys())
    except AttributeError:
        return
    if "version" not in keys:  # pre-0007 database without version column
        return
    exists = store.query_one(
        "SELECT id FROM policy_versions WHERE policy_id = ? AND version = ?",
        (policy_id, row["version"]),
    )
    if exists:
        return
    store.execute(
        "INSERT INTO policy_versions (id, policy_id, version, scope, rules,"
        " effect, effective_from, effective_to, status, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (new_id(), policy_id, row["version"],
         row["scope"] if "scope" in keys else "global", row["rules"],
         row["effect"], row["effective_from"], row["effective_to"],
         row["status"], utcnow_iso()),
    )


def ensure_policy(
    store: OrganizationStore,
    code: str,
    name: str,
    effect: str,
    rules: dict,
    scope: str = "global",
) -> str:
    """Versioned upsert: unchanged content keeps its version, changes bump it."""
    row = store.query_one("SELECT * FROM policies WHERE code = ?", (code,))
    now = utcnow_iso()
    if row is None:
        pid = new_id()
        try:
            store.execute(
                "INSERT INTO policies (id, code, name, rules, effect, scope,"
                " version, status, created_at, updated_at, is_deleted)"
                " VALUES (?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, 0)",
                (pid, code, name, encode_json(rules), effect, scope, now, now),
            )
        except Exception:
            store.execute(
                "INSERT INTO policies (id, code, name, rules, effect, status,"
                " created_at, updated_at, is_deleted)"
                " VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0)",
                (pid, code, name, encode_json(rules), effect, now, now),
            )
            return pid
        _snapshot_policy_version(store, pid)
        return pid
    try:
        current_version = row["version"]
    except (KeyError, IndexError, TypeError):
        current_version = None
    if current_version is None:  # pre-0007 row: plain update, no versioning
        store.execute(
            "UPDATE policies SET name = ?, effect = ?, rules = ?,"
            " status = 'active', updated_at = ? WHERE id = ?",
            (name, effect, encode_json(rules), now, row["id"]),
        )
        return row["id"]
    if row["rules"] == encode_json(rules) and row["effect"] == effect:
        return row["id"]  # idempotent: same content, same version
    store.execute(
        "UPDATE policies SET name = ?, effect = ?, rules = ?, scope = ?,"
        " version = ?, status = 'active', updated_at = ? WHERE id = ?",
        (name, effect, encode_json(rules), scope, current_version + 1, now,
         row["id"]),
    )
    _snapshot_policy_version(store, row["id"])
    return row["id"]
