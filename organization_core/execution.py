"""LONGTHINK ORGANIZATION CORE — Phase 09 Internal Agent execution layer.

Split of responsibilities:
- Organization Core decides WHO / WHAT / WHERE / WHICH AUTHORITY
  (identity, context, Phase 02 authorization — validated BEFORE dispatch).
- Internal Agent decides HOW TO EXECUTE (backend behind InternalAgentPort).

Standardized envelope (spec section Request) is built for every dispatch.
States: ACCEPTED -> RUNNING -> COMPLETED | FAILED | CANCELLED.
The same idempotency_key never executes a consequential action twice.

Real backend mapping (verified in repo, not guessed): the existing Internal
Agent is ``local.agent.FirstBrainAgent.run(TaskInput)`` — an in-process API
with no HTTP surface. ``LocalFirstBrainAdapter`` bridges the envelope onto
it and is opt-in (heavy imports stay out of the default path); the default
backend remains the mock. No other core's code or database is modified.
"""

from __future__ import annotations

from organization_core.adapters import InternalAgentPort, MockInternalAgentAdapter
from organization_core.auth import AuthContext, AuthorizationError, authorize
from organization_core.integration import build_outbound_context, new_correlation_id
from organization_core.models import new_id, utcnow_iso
from organization_core.observability import inc as obs_inc
from organization_core.store import OrganizationStore, decode_json, encode_json
from organization_core.workflows import WorkflowError

TERMINAL = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
RUNNING_STATES = frozenset({"ACCEPTED", "RUNNING"})


def build_envelope(
    store: OrganizationStore,
    actor_person_id: str,
    action: str,
    resource: str = "",
    task: dict | None = None,
    project_id: str | None = None,
    department_id: str | None = None,
    idempotency_key: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Standardized adapter request envelope (spec shape)."""
    outbound = build_outbound_context(
        store, actor_person_id, project_id=project_id,
        department_id=department_id)
    return {
        "actor": {"actor_id": outbound["actor_id"],
                  "role": outbound["role"]},
        "organization_context": {
            "organization_id": outbound["organization_id"],
            "department_id": outbound["department_id"],
        },
        "project_context": {"project_id": outbound["project_id"]},
        "permission": {"permissions": outbound["permissions"]},
        "task": task or {},
        "action": {"action": action, "resource": resource,
                   "extra": extra or {}},
        "correlation_id": outbound["correlation_id"],
        "idempotency_key": idempotency_key or "",
    }


def _audit(store: OrganizationStore, actor: str, execution_id: str,
           status: str, note: str = "") -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, ?, 'agent_execution', ?, ?, ?)",
        (new_id(), actor, f"execution.{status.lower()}", execution_id,
         encode_json({"status": status, "note": note}), utcnow_iso()),
    )


def _set_status(store: OrganizationStore, execution_id: str, status: str,
                result: dict | None = None, error: str | None = None,
                backend_task_id: str | None = None) -> dict:
    store.execute(
        "UPDATE agent_executions SET status = ?, result = COALESCE(?, result),"
        " error = COALESCE(?, error),"
        " backend_task_id = COALESCE(?, backend_task_id), updated_at = ?"
        " WHERE id = ?",
        (status,
         encode_json(result) if result is not None else None, error,
         backend_task_id, utcnow_iso(), execution_id),
    )
    return get_execution(store, execution_id)


def get_execution(store: OrganizationStore, execution_id: str) -> dict:
    row = store.query_one(
        "SELECT * FROM agent_executions WHERE id = ? AND is_deleted = 0",
        (execution_id,),
    )
    if row is None:
        raise LookupError(f"Execution not found: {execution_id}")
    item = dict(row)
    item["envelope"] = decode_json(item.get("envelope"))
    item["permission_snapshot"] = decode_json(item.get("permission_snapshot"))
    item["result"] = decode_json(item.get("result"))
    return item


def submit_execution(
    store: OrganizationStore,
    backend: InternalAgentPort,
    actor_person_id: str,
    action: str,
    resource: str = "",
    task: dict | None = None,
    project_id: str | None = None,
    department_id: str | None = None,
    idempotency_key: str | None = None,
    extra: dict | None = None,
) -> tuple[dict, bool]:
    """Gate on authorization, then dispatch. Returns (record, is_duplicate)."""
    if idempotency_key:
        existing = store.query_one(
            "SELECT id FROM agent_executions WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        if existing:
            return get_execution(store, existing["id"]), True
    envelope = build_envelope(store, actor_person_id, action, resource, task,
                              project_id, department_id, idempotency_key,
                              extra)
    decision = authorize(
        store, actor_person_id=actor_person_id, action=action,
        resource=resource or "task",
        ctx=AuthContext(project_id=project_id,
                        department_id=department_id))
    if not decision.allow:
        _audit(store, actor_person_id, idempotency_key or "none", "DENIED",
               decision.reason)
        raise AuthorizationError(
            f"execution denied, never dispatched: {decision.reason}")
    now = utcnow_iso()
    execution_id = new_id()
    store.execute(
        "INSERT INTO agent_executions (id, idempotency_key, actor_person_id,"
        " action, resource, project_id, department_id, envelope,"
        " permission_snapshot, correlation_id, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACCEPTED', ?,"
        " ?, 0)",
        (execution_id, idempotency_key, actor_person_id, action, resource,
         project_id, department_id, encode_json(envelope),
         encode_json(envelope["permission"]), envelope["correlation_id"],
         now, now),
    )
    _audit(store, actor_person_id, execution_id, "ACCEPTED", action)
    _set_status(store, execution_id, "RUNNING")
    _audit(store, actor_person_id, execution_id, "RUNNING", action)
    try:
        result = backend.execute(f"{action}.{resource}" if resource else action,
                                 envelope)
    except Exception as exc:
        _set_status(store, execution_id, "FAILED", error=str(exc)[:500])
        obs_inc("org_internal_agent_failures_total")
        _audit(store, actor_person_id, execution_id, "FAILED", str(exc)[:200])
        record = get_execution(store, execution_id)
        record["failed"] = True
        return record, False
    status = "COMPLETED" if str(result.get("status", "")).lower() not in (
        "failed", "error") else "FAILED"
    if status == "FAILED":
        obs_inc("org_internal_agent_failures_total")
    record = _set_status(store, execution_id, status, result=result,
                         backend_task_id=result.get("task_id"))
    _audit(store, actor_person_id, execution_id, status, action)
    return record, False


def poll_execution(store: OrganizationStore, backend: InternalAgentPort,
                   execution_id: str) -> dict:
    """Status polling; refreshes non-terminal records from the backend."""
    record = get_execution(store, execution_id)
    if record["status"] in RUNNING_STATES and record.get("backend_task_id"):
        try:
            live = backend.get_status(record["backend_task_id"])
        except Exception:
            live = {}
        if str(live.get("status", "")).lower() == "completed":
            record = _set_status(store, execution_id, "COMPLETED")
        elif str(live.get("status", "")).lower() in ("failed", "error"):
            record = _set_status(store, execution_id, "FAILED",
                                 error=str(live.get("error", ""))[:500])
    return record


def cancel_execution(store: OrganizationStore, backend: InternalAgentPort,
                     execution_id: str, actor_person_id: str) -> dict:
    record = get_execution(store, execution_id)
    if record["status"] in TERMINAL:
        raise WorkflowError(
            f"cannot cancel terminal execution ({record['status']})")
    try:
        backend.cancel(record.get("backend_task_id") or execution_id)
    except Exception as exc:
        record = _set_status(store, execution_id, "CANCELLED",
                             error=f"cancel best-effort: {exc}"[:500])
    else:
        record = _set_status(store, execution_id, "CANCELLED")
    _audit(store, actor_person_id, execution_id, "CANCELLED", "user cancel")
    return record


class LocalFirstBrainAdapter(InternalAgentPort):
    """Opt-in bridge onto the existing ``FirstBrainAgent`` (verified shape).

    Maps envelope -> ``TaskInput(question, project_id)`` and ``TaskResult``
    -> execution result. Synchronous: no CANCEL support (reports it).
    """

    def __init__(self, runner=None) -> None:
        # Injectable runner(task_input) -> object with .answer (tests seam).
        self._runner = runner

    def _run(self, question: str, project_id: str | None):
        if self._runner is not None:
            return self._runner(question, project_id)
        from local.agent import FirstBrainAgent, TaskInput

        return FirstBrainAgent().run(
            TaskInput(question=question, project_id=project_id))

    def execute(self, action: str, payload: dict) -> dict:
        task = payload.get("task") or {}
        project = (payload.get("project_context") or {}).get("project_id")
        question = str(task.get("question") or task.get("title")
                       or f"Execute {action}")
        result = self._run(question, project)
        answer = getattr(result, "answer", str(result))
        return {"backend": "local-first-brain", "status": "completed",
                "action": action, "task_id": new_correlation_id(),
                "answer": answer[:2000]}

    def get_status(self, task_id: str) -> dict:
        return {"backend": "local-first-brain", "task_id": task_id,
                "status": "completed"}

    def cancel(self, task_id: str) -> dict:
        return {"backend": "local-first-brain", "task_id": task_id,
                "status": "not_supported",
                "reason": "synchronous runner cannot cancel"}


def build_internal_adapter(kind: str = "mock",
                           runner=None) -> InternalAgentPort:
    if kind == "local":
        return LocalFirstBrainAdapter(runner=runner)
    return MockInternalAgentAdapter()
