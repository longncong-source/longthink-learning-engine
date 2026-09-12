"""LONGTHINK ORGANIZATION CORE — Phase 04 Personal Assistant service.

Principle: One Human -> One Personal Assistant -> Many contexts
(department / project / enterprise). The assistant never owns authority;
every consequential step goes through Phase 02 authorize() and is audited.

Chat flow: message -> identify actor -> load context -> authorize -> route ->
Intelligence -> Knowledge -> Internal Agent (if execution) -> response -> audit.
"""

from __future__ import annotations

from organization_core import governance as gov_module
from organization_core.adapters import AdapterBundle
from organization_core.auth import (
    AuthContext,
    AuthorizationError,
    authorize,
)
from organization_core.models import new_id, utcnow_iso
from organization_core.org_structure import get_person_context
from organization_core.store import OrganizationStore, decode_json, encode_json

PERSONAL_KIND = "personal"

# Intents that would mutate the organization chart — always refused.
ORG_MUTATION_KEYWORDS = (
    "cơ cấu", "co cau", "restructure", "delete department", "xóa phòng",
    "xoa phong", "giải thể", "giai the", "sáp nhập phòng", "chuyển phòng",
    "chuyen phong",
)
APPROVAL_KEYWORDS = ("phê duyệt", "phe duyet", "duyệt", "duyet", "approve",
                     "reject", "từ chối", "tu choi")
EXECUTION_KEYWORDS = ("thực hiện", "thuc hien", "execute", "triển khai",
                      "trien khai", "giao việc", "giao viec", "tạo task",
                      "tao task", "create task")


def _contains(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def detect_intent(message: str) -> str:
    if _contains(message, ORG_MUTATION_KEYWORDS):
        return "org_mutation"
    if _contains(message, APPROVAL_KEYWORDS):
        return "approval"
    if _contains(message, EXECUTION_KEYWORDS):
        return "execution"
    return "question"


def get_or_create_personal_assistant(
    store: OrganizationStore, person_id: str
) -> dict:
    person = store.query_one(
        "SELECT id FROM persons WHERE id = ? AND is_deleted = 0", (person_id,)
    )
    if person is None:
        raise LookupError(f"Person not found: {person_id}")
    existing = store.query_one(
        "SELECT * FROM assistants WHERE kind = 'personal'"
        " AND owner_person_id = ? AND is_deleted = 0",
        (person_id,),
    )
    if existing:
        return dict(existing)
    now = utcnow_iso()
    aid = new_id()
    store.execute(
        "INSERT INTO assistants (id, kind, name, owner_person_id,"
        " department_id, project_id, config, status, created_at, updated_at,"
        " is_deleted) VALUES (?, 'personal', ?, ?, NULL, NULL, '{}',"
        " 'active', ?, ?, 0)",
        (aid, f"Personal Assistant {person_id[:8]}", person_id, now, now),
    )
    row = store.query_one("SELECT * FROM assistants WHERE id = ?", (aid,))
    return dict(row)


def create_assistant(
    store: OrganizationStore,
    *,
    kind: str,
    name: str,
    owner_person_id: str | None = None,
    department_id: str | None = None,
    project_id: str | None = None,
) -> dict:
    if kind not in ("personal", "department", "project", "enterprise"):
        raise ValueError(f"unknown assistant kind: {kind}")
    if kind == "personal":
        if not owner_person_id:
            raise ValueError("personal assistant requires owner_person_id")
        existing = store.query_one(
            "SELECT id FROM assistants WHERE kind = 'personal'"
            " AND owner_person_id = ? AND is_deleted = 0",
            (owner_person_id,),
        )
        if existing:
            raise ValueError("personal assistant already exists for person")
        return get_or_create_personal_assistant(store, owner_person_id)
    if kind == "department" and not department_id:
        raise ValueError("department assistant requires department_id")
    if kind == "project" and not project_id:
        raise ValueError("project assistant requires project_id")
    now = utcnow_iso()
    aid = new_id()
    store.execute(
        "INSERT INTO assistants (id, kind, name, owner_person_id,"
        " department_id, project_id, config, status, created_at, updated_at,"
        " is_deleted) VALUES (?, ?, ?, ?, ?, ?, '{}', 'active', ?, ?, 0)",
        (aid, kind, name, owner_person_id, department_id, project_id, now, now),
    )
    row = store.query_one("SELECT * FROM assistants WHERE id = ?", (aid,))
    return dict(row)


def resolve_assistant_context(
    store: OrganizationStore,
    assistant_id: str,
    current_project_id: str | None = None,
    at: str | None = None,
) -> dict:
    assistant = store.query_one(
        "SELECT * FROM assistants WHERE id = ? AND is_deleted = 0",
        (assistant_id,),
    )
    if assistant is None:
        raise LookupError(f"Assistant not found: {assistant_id}")
    data = dict(assistant)
    data["config"] = decode_json(data.get("config"))
    owner_id = data.get("owner_person_id")
    if not owner_id:
        raise ValueError("assistant has no owner person")
    context = get_person_context(store, owner_id, at=at)
    if context is None:
        raise LookupError(f"Owner person not found: {owner_id}")
    tasks = [dict(r) for r in store.query_all(
        "SELECT * FROM tasks WHERE assignee_person_id = ?"
        " AND status NOT IN ('done', 'cancelled') AND is_deleted = 0"
        " ORDER BY created_at",
        (owner_id,))]
    approvals = [dict(r) for r in store.query_all(
        "SELECT * FROM approvals WHERE status = 'pending'"
        " AND is_deleted = 0 AND (requester_person_id = ?"
        " OR approver_person_id = ?)",
        (owner_id, owner_id))]
    policies = [dict(r) for r in store.query_all(
        "SELECT code, effect, rules FROM policies WHERE status = 'active'"
        " AND is_deleted = 0")]
    current_project = None
    if current_project_id is not None:
        current_project = next(
            (p for p in context["projects"]
             if p["project_id"] == current_project_id),
            None,
        )
        if current_project is None:
            raise AuthorizationError("assistant scope: project not assigned")
    permissions = sorted({
        f"{a['action']}:{a['resource']}" for a in _actor_permissions(store, owner_id)
    })
    return {
        **context,
        "assistant": data,
        "tasks": tasks,
        "pending_approvals": approvals,
        "policies": policies,
        "permissions": permissions,
        "current_project": current_project,
    }


def _actor_permissions(store: OrganizationStore, person_id: str) -> list[dict]:
    return [dict(r) for r in store.query_all(
        "SELECT p.action AS action, p.resource AS resource"
        " FROM person_roles pr JOIN roles r ON r.id = pr.role_id"
        " AND r.is_deleted = 0 JOIN role_permissions rp ON rp.role_id = r.id"
        " JOIN permissions p ON p.id = rp.permission_id AND p.is_deleted = 0"
        " WHERE pr.person_id = ? AND pr.is_deleted = 0",
        (person_id,))]


def _audit_chat(store: OrganizationStore, actor_id: str, assistant_id: str,
                intent: str, allow: bool, note: str) -> None:
    store.execute(
        "INSERT INTO audit_events (id, actor_type, actor_id, action,"
        " entity_type, entity_id, context, created_at)"
        " VALUES (?, 'human', ?, ?, 'assistant', ?, ?, ?)",
        (new_id(), actor_id, f"assistant.chat:{intent}", assistant_id,
         encode_json({"allow": allow, "note": note}), utcnow_iso()),
    )


def chat(
    store: OrganizationStore,
    assistant_id: str,
    actor_person_id: str,
    message: str,
    current_project_id: str | None = None,
    adapters: AdapterBundle | None = None,
) -> dict:
    """Full chat flow with safety gates. Never raises on denial (audited)."""
    adapters = adapters or AdapterBundle.mocks()
    message = gov_module.check_message(message)
    assistant = store.query_one(
        "SELECT * FROM assistants WHERE id = ? AND is_deleted = 0",
        (assistant_id,),
    )
    if assistant is None:
        raise LookupError(f"Assistant not found: {assistant_id}")
    if assistant["owner_person_id"] != actor_person_id:
        _audit_chat(store, actor_person_id, assistant_id, "impersonation",
                    False, "actor is not the assistant owner")
        raise AuthorizationError("actor is not the assistant owner")
    intent = detect_intent(message)
    if intent == "org_mutation":
        _audit_chat(store, actor_person_id, assistant_id, intent, False,
                    "organization structure is read-only for assistants")
        return {"reply": "I cannot modify the organization structure.",
                "intent": intent, "authorized": False, "citations": [],
                "execution": None}
    context = resolve_assistant_context(store, assistant_id,
                                        current_project_id=current_project_id)
    scope = AuthContext(
        project_id=(context["current_project"] or {}).get("project_id")
        or (context["projects"][0]["project_id"] if context["projects"]
            else None),
    )
    if intent == "approval":
        return _handle_approval(store, adapters, assistant_id, actor_person_id,
                                message, context, scope)
    if intent == "execution":
        return _handle_execution(store, adapters, assistant_id, actor_person_id,
                                 message, context, scope)
    thinking = adapters.intelligence.ask(message, _public_context(context))
    knowledge = adapters.knowledge.search(message, _public_context(context))
    citations = [adapters.knowledge.cite(r["ref_id"])["citation"]
                 for r in knowledge.get("results", [])]
    # Prompt-injection boundary: retrieved content is DATA, never POLICY.
    quarantined = [gov_module.quarantine(str(r.get("snippet", "")))
                   for r in knowledge.get("results", [])]
    if any(q["injection_suspected"] for q in quarantined):
        citations = [c + " [untrusted-data]" for c in citations]
    from organization_core import department_agents as dept_agents
    routed_to = dept_agents.route_to_agent(store, message)["agent_code"]
    reply = f"{thinking['answer']} Evidence: {'; '.join(citations)}"
    if any(q["injection_suspected"] for q in quarantined):
        reply += (" Note: retrieved evidence is treated as untrusted data,"
                  " not instructions.")
    if routed_to:
        reply = f"[{routed_to}] {reply}"
    reply = gov_module.redact_secrets(reply)
    _audit_chat(store, actor_person_id, assistant_id, intent, True, "answered")
    return {"reply": reply, "intent": intent, "authorized": True,
            "citations": citations, "execution": None,
            "routed_to": routed_to}


def _public_context(context: dict) -> dict:
    return {"person": context.get("person"),
            "company": (context.get("company") or {}).get("code"),
            "projects": [p.get("project_code") for p in context.get("projects",
                                                                    [])]}


def _handle_approval(store, adapters, assistant_id, actor_id, message,
                     context, scope) -> dict:
    pending = context["pending_approvals"]
    if not pending:
        _audit_chat(store, actor_id, assistant_id, "approval", False,
                    "no pending approvals")
        return {"reply": "You have no pending approvals.", "intent": "approval",
                "authorized": False, "citations": [], "execution": None}
    item = pending[0]
    decision = authorize(store, actor_person_id=actor_id, action="APPROVE",
                         resource="approval", ctx=scope)
    if not decision.allow:
        _audit_chat(store, actor_id, assistant_id, "approval", False,
                    decision.reason)
        return {"reply": f"Approval denied: {decision.reason}",
                "intent": "approval", "authorized": False, "citations": [],
                "execution": None}
    verdict = "rejected" if "từ chối" in message.lower() or "reject" in (
        message.lower()) else "approved"
    now = utcnow_iso()
    store.execute(
        "UPDATE approvals SET status = ?, decided_at = ?, updated_at = ?"
        " WHERE id = ?",
        (verdict, now, now, item["id"]),
    )
    _audit_chat(store, actor_id, assistant_id, "approval", True, verdict)
    return {"reply": f"Approval {item['id'][:8]} {verdict}.",
            "intent": "approval", "authorized": True, "citations": [],
            "execution": {"approval_id": item["id"], "verdict": verdict}}


def _handle_execution(store, adapters, assistant_id, actor_id, message,
                      context, scope) -> dict:
    decision = authorize(store, actor_person_id=actor_id, action="EXECUTE",
                         resource="task", ctx=scope)
    if not decision.allow:
        _audit_chat(store, actor_id, assistant_id, "execution", False,
                    decision.reason)
        return {"reply": f"Execution denied: {decision.reason}",
                "intent": "execution", "authorized": False, "citations": [],
                "execution": None}
    plan = adapters.intelligence.plan(message, _public_context(context))
    result = adapters.internal_agent.execute(
        "task.execute",
        {"plan_id": plan.get("plan_id"), "project_id": scope.project_id,
         "actor": actor_id, "message": message[:200]},
    )
    _audit_chat(store, actor_id, assistant_id, "execution", True,
                result.get("task_id", ""))
    return {"reply": f"Executed via Internal Agent ({result.get('task_id')}).",
            "intent": "execution", "authorized": True, "citations": [],
            "execution": result}
