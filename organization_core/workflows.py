"""LONGTHINK ORGANIZATION CORE — Phase 07 workflow, task & approval (HITL).

State machine: DRAFT -> SUBMITTED -> IN_REVIEW -> APPROVED/REJECTED ->
IN_PROGRESS -> COMPLETED, plus CANCELLED. Extensible per workflow via
definition["transitions"].

HITL: consequential actions (contract signing, payments, budget changes,
org-authority changes, critical baseline changes) REQUIRE an approved
approval record. Agents may prepare/recommend/route/execute-after-approval
but never decide when human approval is required.

Idempotency: approvals carry a UNIQUE idempotency_key (re-post returns the
existing record); consequential execution is keyed by approval id
(duplicate execution returns the first result, never re-executes).
"""

from __future__ import annotations

import json

from organization_core.adapters import AdapterBundle
from organization_core.auth import authorize
from organization_core.models import new_id, utcnow_iso
from organization_core.observability import inc as obs_inc
from organization_core.observability import timed as obs_timed
from organization_core.store import OrganizationStore, decode_json, encode_json

STATES = ("DRAFT", "SUBMITTED", "IN_REVIEW", "APPROVED", "REJECTED",
          "IN_PROGRESS", "COMPLETED", "CANCELLED")

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "DRAFT": ("SUBMITTED", "CANCELLED"),
    "SUBMITTED": ("IN_REVIEW", "CANCELLED"),
    "IN_REVIEW": ("APPROVED", "REJECTED", "CANCELLED"),
    "APPROVED": ("IN_PROGRESS", "CANCELLED"),
    "REJECTED": ("DRAFT", "CANCELLED"),
    "IN_PROGRESS": ("COMPLETED", "CANCELLED"),
    "COMPLETED": (),
    "CANCELLED": (),
}

# (action, resource) pairs that always require human approval.
CONSEQUENTIAL: frozenset[tuple[str, str]] = frozenset({
    ("EXECUTE", "contract"),      # sign contract
    ("EXECUTE", "payment"),       # approve payment
    ("UPDATE", "budget"),         # change budget
    ("UPDATE", "org_authority"),  # change organizational authority
    ("UPDATE", "baseline"),       # change critical project baseline
})


class WorkflowError(ValueError):
    pass


class ApprovalExpired(WorkflowError):
    pass


def _audit(store: OrganizationStore, actor: str | None, action: str,
           entity: str, entity_id: str, note: str) -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, ?, ?, ?, ?, ?)",
        (new_id(), actor, action, entity, entity_id,
         encode_json({"note": note}), utcnow_iso()),
    )


def allowed_transitions(definition: dict, state: str) -> tuple[str, ...]:
    custom = (definition or {}).get("transitions")
    if isinstance(custom, dict) and state in custom:
        return tuple(custom[state])
    return TRANSITIONS.get(state, ())


# --- workflows -------------------------------------------------------------


def create_workflow(store: OrganizationStore, code: str, name: str,
                    definition: dict | None = None) -> dict:
    row = store.query_one("SELECT * FROM workflows WHERE code = ?", (code,))
    if row:
        return dict(row)
    now = utcnow_iso()
    wid = new_id()
    store.execute(
        "INSERT INTO workflows (id, code, name, version, definition, status,"
        " created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, 1, ?, 'active', ?, ?, 0)",
        (wid, code, name, encode_json(definition or {}), now, now),
    )
    return dict(store.query_one("SELECT * FROM workflows WHERE id = ?",
                                (wid,)))


def start_instance(store: OrganizationStore, workflow_id: str,
                   business_ref_type: str | None = None,
                   business_ref_id: str | None = None) -> dict:
    now = utcnow_iso()
    iid = new_id()
    store.execute(
        "INSERT INTO workflow_instances (id, workflow_id, business_ref_type,"
        " business_ref_id, status, current_step, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, ?, 'DRAFT', 'start', ?, ?, 0)",
        (iid, workflow_id, business_ref_type, business_ref_id, now, now),
    )
    return dict(store.query_one(
        "SELECT * FROM workflow_instances WHERE id = ?", (iid,)))


def transition_instance(store: OrganizationStore, instance_id: str,
                        to_state: str,
                        actor_person_id: str | None = None) -> dict:
    if to_state not in STATES:
        obs_inc("org_workflow_failures_total", {"op": "transition"})
        raise WorkflowError(f"unknown state: {to_state}")
    row = store.query_one(
        "SELECT * FROM workflow_instances WHERE id = ? AND is_deleted = 0",
        (instance_id,),
    )
    if row is None:
        raise LookupError(f"Instance not found: {instance_id}")
    current = row["status"]
    if current == to_state:  # idempotent re-transition
        return dict(row)
    wf = store.query_one("SELECT definition FROM workflows WHERE id = ?",
                         (row["workflow_id"],))
    definition = decode_json(wf["definition"]) if wf else {}
    if to_state not in allowed_transitions(definition, current):
        obs_inc("org_workflow_failures_total", {"op": "transition"})
        raise WorkflowError(f"invalid transition {current} -> {to_state}")
    now = utcnow_iso()
    store.execute(
        "UPDATE workflow_instances SET status = ?, current_step = ?,"
        " updated_at = ? WHERE id = ?",
        (to_state, to_state.lower(), now, instance_id),
    )
    _audit(store, actor_person_id, "workflow.transition", "workflow_instance",
           instance_id, f"{current} -> {to_state}")
    return dict(store.query_one(
        "SELECT * FROM workflow_instances WHERE id = ?", (instance_id,)))


# --- tasks -----------------------------------------------------------------


def create_task(store: OrganizationStore, title: str,
                owner_person_id: str | None = None,
                assignee_person_id: str | None = None,
                department_id: str | None = None,
                project_id: str | None = None,
                priority: str = "normal",
                due_at: str | None = None,
                dependencies: list[str] | None = None,
                source: str | None = None) -> dict:
    now = utcnow_iso()
    tid = new_id()
    store.execute(
        "INSERT INTO tasks (id, project_id, assignee_person_id, title,"
        " status, priority, due_at, owner_person_id, department_id,"
        " dependencies, source, created_at, updated_at, is_deleted)"
        " VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, 0)",
        (tid, project_id, assignee_person_id, title, priority, due_at,
         owner_person_id, department_id, json.dumps(dependencies or []),
         source, now, now),
    )
    return dict(store.query_one("SELECT * FROM tasks WHERE id = ?", (tid,)))


def update_task(store: OrganizationStore, task_id: str,
                fields: dict) -> dict:
    allowed = {"title", "status", "priority", "due_at", "assignee_person_id",
               "owner_person_id", "department_id", "dependencies", "source"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        raise WorkflowError("no updatable fields")
    if "dependencies" in updates and not isinstance(updates["dependencies"],
                                                    str):
        updates["dependencies"] = json.dumps(updates["dependencies"])
    row = store.query_one(
        "SELECT id FROM tasks WHERE id = ? AND is_deleted = 0", (task_id,))
    if row is None:
        raise LookupError(f"Task not found: {task_id}")
    store.execute(
        f"UPDATE tasks SET {', '.join(f'{k} = ?' for k in updates)},"
        " updated_at = ? WHERE id = ?",
        (*updates.values(), utcnow_iso(), task_id),
    )
    return dict(store.query_one("SELECT * FROM tasks WHERE id = ?", (task_id,)))


# --- approvals (HITL) --------------------------------------------------------


def _policy_snapshot(store: OrganizationStore) -> dict:
    rows = store.query_all(
        "SELECT code, effect, rules FROM policies WHERE status = 'active'"
        " AND is_deleted = 0")
    return {r["code"]: {"effect": r["effect"], "rules": r["rules"]}
            for r in rows}


def hitl_required(store: OrganizationStore, action: str,
                  resource: str) -> bool:
    if (action, resource) in CONSEQUENTIAL:
        return True
    now = utcnow_iso()
    rows = store.query_all(
        "SELECT rules, effective_from, effective_to FROM policies"
        " WHERE effect = 'require_approval' AND status = 'active'"
        " AND is_deleted = 0")
    for row in rows:
        rules = decode_json(row["rules"])
        actions = rules.get("actions", [])
        resources = rules.get("resources", [])
        action_ok = not actions or actions == "*" or action in actions
        resource_ok = (not resources or resources == "*"
                       or resource in resources)
        if not (action_ok and resource_ok):
            continue
        frm, to = row["effective_from"], row["effective_to"]
        if (not frm or now >= str(frm)) and (not to or now <= str(to)):
            return True
    return False


def request_approval(
    store: OrganizationStore,
    requested_by: str,
    action: str,
    resource: str,
    reason: str = "",
    approver_person_id: str | None = None,
    approver_role_id: str | None = None,
    workflow_instance_id: str | None = None,
    idempotency_key: str | None = None,
    expires_at: str | None = None,
) -> dict:
    if idempotency_key:
        existing = store.query_one(
            "SELECT * FROM approvals WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if existing:  # duplicate submission -> same record
            return dict(existing)
    now = utcnow_iso()
    aid = new_id()
    store.execute(
        "INSERT INTO approvals (id, workflow_instance_id, requester_person_id,"
        " approver_person_id, approver_role_id, action, resource, reason,"
        " status, policy_snapshot, idempotency_key, expires_at, created_at,"
        " updated_at, is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending',"
        " ?, ?, ?, ?, ?, 0)",
        (aid, workflow_instance_id, requested_by, approver_person_id,
         approver_role_id, action, resource, reason,
         encode_json(_policy_snapshot(store)), idempotency_key, expires_at,
         now, now),
    )
    _audit(store, requested_by, "approval.request", "approval", aid,
           f"{action}:{resource}")
    return dict(store.query_one("SELECT * FROM approvals WHERE id = ?",
                                (aid,)))


def _approval_is_expired(item: dict, now: str) -> bool:
    return bool(item.get("expires_at") and now > str(item["expires_at"]))


def decide_approval(store: OrganizationStore, approval_id: str,
                    approver_person_id: str, verdict: str,
                    reason: str = "") -> dict:
    with obs_timed("org_approval_latency_seconds"):
        return _decide_approval(store, approval_id, approver_person_id,
                                verdict, reason)


def _decide_approval(store: OrganizationStore, approval_id: str,
                     approver_person_id: str, verdict: str,
                     reason: str = "") -> dict:
    if verdict not in ("approved", "rejected"):
        obs_inc("org_workflow_failures_total", {"op": "decide"})
        raise WorkflowError(f"unknown verdict: {verdict}")
    item = store.query_one(
        "SELECT * FROM approvals WHERE id = ? AND is_deleted = 0",
        (approval_id,),
    )
    if item is None:
        raise LookupError(f"Approval not found: {approval_id}")
    if item["status"] != "pending":
        return dict(item)  # idempotent re-decision
    now = utcnow_iso()
    if _approval_is_expired(dict(item), now):
        store.execute(
            "UPDATE approvals SET status = 'expired', updated_at = ?"
            " WHERE id = ?",
            (now, approval_id),
        )
        _audit(store, approver_person_id, "approval.expired", "approval",
               approval_id, "decided after expiry")
        obs_inc("org_workflow_failures_total", {"op": "decide"})
        raise ApprovalExpired("approval expired")
    designated = item["approver_person_id"]
    if designated and designated != approver_person_id:
        obs_inc("org_workflow_failures_total", {"op": "decide"})
        raise WorkflowError("approver mismatch")
    decision = authorize(store, actor_person_id=approver_person_id,
                         action="APPROVE", resource=item["resource"] or "task")
    if not decision.allow:
        raise WorkflowError(f"approver not authorized: {decision.reason}")
    store.execute(
        "UPDATE approvals SET status = ?, decision = ?, decided_at = ?,"
        " reason = ?, updated_at = ? WHERE id = ?",
        (verdict, verdict, now, reason or item["reason"], now, approval_id),
    )
    _audit(store, approver_person_id, f"approval.{verdict}", "approval",
           approval_id, reason)
    return dict(store.query_one("SELECT * FROM approvals WHERE id = ?",
                                (approval_id,)))


def escalate_approval(store: OrganizationStore, approval_id: str,
                      by_person_id: str, to_person_id: str | None = None,
                      to_role_id: str | None = None,
                      reason: str = "") -> dict:
    item = store.query_one(
        "SELECT * FROM approvals WHERE id = ? AND is_deleted = 0",
        (approval_id,),
    )
    if item is None:
        raise LookupError(f"Approval not found: {approval_id}")
    if item["status"] != "pending":
        raise WorkflowError("only pending approvals can be escalated")
    now = utcnow_iso()
    store.execute(
        "UPDATE approvals SET approver_person_id = ?, approver_role_id = ?,"
        " reason = ?, updated_at = ? WHERE id = ?",
        (to_person_id, to_role_id, reason or item["reason"], now, approval_id),
    )
    _audit(store, by_person_id, "approval.escalate", "approval", approval_id,
           reason)
    return dict(store.query_one("SELECT * FROM approvals WHERE id = ?",
                                (approval_id,)))


def expire_overdue(store: OrganizationStore) -> int:
    now = utcnow_iso()
    rows = store.query_all(
        "SELECT id FROM approvals WHERE status = 'pending'"
        " AND is_deleted = 0 AND expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    )
    for row in rows:
        store.execute(
            "UPDATE approvals SET status = 'expired', updated_at = ?"
            " WHERE id = ?",
            (now, row["id"]),
        )
        _audit(store, None, "approval.expired", "approval", row["id"],
               "overdue sweep")
    return len(rows)


# --- consequential execution (agent: execute AFTER approval only) -----------


def execute_consequential(
    store: OrganizationStore,
    approval_id: str,
    executor_person_id: str,
    adapters: AdapterBundle | None = None,
) -> dict:
    """Run a consequential action exactly once per approved approval."""
    adapters = adapters or AdapterBundle.mocks()
    item = store.query_one(
        "SELECT * FROM approvals WHERE id = ? AND is_deleted = 0",
        (approval_id,),
    )
    if item is None:
        raise LookupError(f"Approval not found: {approval_id}")
    if item["status"] != "approved":
        raise WorkflowError(
            f"execution requires an approved approval (got {item['status']})")
    prior = store.query_one(
        "SELECT * FROM audit_events WHERE action = 'consequential.executed'"
        " AND entity_id = ?",
        (approval_id,),
    )
    if prior:  # duplicate execution -> first result, never re-executes
        return {"status": "duplicate", "approval_id": approval_id,
                "task_id": decode_json(prior["context"]).get("task_id")}
    result = adapters.internal_agent.execute(
        f"{item['action']}.{item['resource']}",
        {"approval_id": approval_id, "executor": executor_person_id},
    )
    agent_status = result.get("status")
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, 'consequential.executed', 'approval', ?,"
        " ?, ?)",
        (new_id(), executor_person_id, approval_id,
         encode_json({"task_id": result.get("task_id")}), utcnow_iso()),
    )
    return {"approval_id": approval_id, "agent_status": agent_status,
            "status": "executed", **{k: v for k, v in result.items()
                                     if k != "status"}}
