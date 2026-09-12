"""LONGTHINK ORGANIZATION CORE — REST API (standalone FastAPI app, Phases 03-04).

Follows the existing stack (FastAPI, ``/health`` without auth, ``/v1/*``).
Runs on its OWN database via OrganizationStore — never touches the
Second/First/Mid Brain databases. Mount/embed decisions belong to Phase 08+.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Header, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from organization_core import assistant as assistant_service
from organization_core import department_agents as dept_agents
from organization_core import enterprise as ent_service
from organization_core import execution as exec_service
from organization_core import governance as gov_service
from organization_core import observability as obs
from organization_core import org_structure
from organization_core import project_agents as proj_agents
from organization_core import workflows as wf_service
from organization_core.auth import AuthorizationError
from organization_core.integration import CoreClientError, adapters_from_env
from organization_core.seed import seed_dak
from organization_core.store import OrganizationStore


class AssistantCreate(BaseModel):
    kind: str = "personal"
    name: str = ""
    owner_person_id: str | None = None
    department_id: str | None = None
    project_id: str | None = None


class ChatRequest(BaseModel):
    actor_person_id: str
    message: str
    current_project_id: str | None = None


class RouteRequest(BaseModel):
    message: str
    candidates: list[str] | None = None


class CoordinateRequest(BaseModel):
    actor_person_id: str
    message: str
    agents: list[str] | None = None


class WorkflowCreate(BaseModel):
    code: str
    name: str
    definition: dict | None = None


class InstanceCreate(BaseModel):
    workflow_id: str
    business_ref_type: str | None = None
    business_ref_id: str | None = None


class TransitionRequest(BaseModel):
    to_state: str
    actor_person_id: str | None = None


class TaskCreate(BaseModel):
    title: str
    owner_person_id: str | None = None
    assignee_person_id: str | None = None
    department_id: str | None = None
    project_id: str | None = None
    priority: str = "normal"
    due_at: str | None = None
    dependencies: list[str] | None = None
    source: str | None = None


class ApprovalCreate(BaseModel):
    requested_by: str
    action: str
    resource: str = "task"
    reason: str = ""
    approver_person_id: str | None = None
    approver_role_id: str | None = None
    workflow_instance_id: str | None = None
    idempotency_key: str | None = None
    expires_at: str | None = None


class DecideRequest(BaseModel):
    approver_person_id: str
    verdict: str
    reason: str = ""


class EscalateRequest(BaseModel):
    by_person_id: str
    to_person_id: str | None = None
    to_role_id: str | None = None
    reason: str = ""


class ExecuteRequest(BaseModel):
    executor_person_id: str


class DispatchRequest(BaseModel):
    actor_person_id: str
    action: str
    resource: str = ""
    task: dict | None = None
    project_id: str | None = None
    department_id: str | None = None
    idempotency_key: str | None = None
    extra: dict | None = None


class CancelExecutionRequest(BaseModel):
    actor_person_id: str


class BriefRequest(BaseModel):
    actor_person_id: str


class EnterpriseActRequest(BaseModel):
    actor_person_id: str
    verb: str
    action: str = ""
    resource: str = ""
    context: dict | None = None


def _store(app: FastAPI) -> OrganizationStore:
    return app.state.org_store


def _authenticate(api_key: str | None):
    """Phase 11 auth integration point: open when no keys configured."""
    try:
        return gov_service.authenticate_request(api_key)
    except PermissionError as exc:
        return JSONResponse(status_code=401, content={
            "error": {"code": "unauthorized", "message": str(exc)}})


def _rate_limit(identity) -> JSONResponse | None:
    try:
        gov_service.check_rate_limit(identity.subject)
    except PermissionError as exc:
        return JSONResponse(status_code=429, content={
            "error": {"code": "rate_limited", "message": str(exc)}})
    return None


def create_org_app(store: OrganizationStore | None = None) -> FastAPI:
    app = FastAPI(title="LongThink Organization Core", version="0.12.0")

    if store is None:
        store = OrganizationStore("data/organization.sqlite3")
        store.init_schema()
        seed_dak(store)
    app.state.org_store = store
    # Phase 08: HTTP adapters only when env configures core URLs, else mocks.
    app.state.adapters = adapters_from_env()
    dept_agents.ensure_department_agents(store)

    @app.middleware("http")
    async def observability_middleware(request: Request, call_next):
        # Tracing + metrics. Bodies/query strings are never logged.
        request_id = request.headers.get("x-request-id") or obs.new_request_id()
        start = time.perf_counter()
        try:
            response = await call_next(request)
            code = response.status_code
        except Exception:
            obs.inc("org_request_count", {"path": request.url.path,
                                          "code": "500"})
            raise
        latency = time.perf_counter() - start
        obs.inc("org_request_count", {"path": request.url.path,
                                      "code": str(code)})
        obs.observe("org_request_latency_seconds", latency,
                    {"path": request.url.path})
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/ready")
    def ready():
        checks: dict[str, bool] = {}
        try:
            tables = set(_store(app).table_names())
            checks["database"] = True
            checks["schema"] = {"companies", "departments", "persons",
                                "policies", "audit_events"} <= tables
        except Exception:
            checks["database"] = False
            checks["schema"] = False
        if all(checks.values()):
            return {"ready": True, "checks": checks}
        return JSONResponse(status_code=503,
                            content={"ready": False, "checks": checks})

    @app.get("/v1/metrics")
    def metrics() -> dict:
        return obs.snapshot()

    @app.get("/v1/organization")
    def get_organization(at: str | None = Query(default=None)) -> dict:
        return org_structure.get_organization(_store(app), at=at)

    @app.get("/v1/versions")
    def list_versions() -> dict:
        return {"versions": org_structure.list_versions(_store(app))}

    @app.get("/v1/departments")
    def list_departments(
        status: str | None = Query(default=None),
        at: str | None = Query(default=None),
    ) -> dict:
        return {
            "departments": org_structure.list_departments(
                _store(app), status=status, at=at
            )
        }

    @app.get("/v1/departments/{dept_id}")
    def get_department(dept_id: str,
                       at: str | None = Query(default=None)):
        dept = org_structure.get_department(_store(app), dept_id, at=at)
        if dept is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Department not found"}},
            )
        return dept

    @app.get("/v1/people/{person_id}")
    def get_person(person_id: str):
        person = org_structure.get_person(_store(app), person_id)
        if person is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Person not found"}},
            )
        return person

    @app.get("/v1/people/{person_id}/context")
    def get_person_context(person_id: str,
                           at: str | None = Query(default=None)):
        context = org_structure.get_person_context(_store(app), person_id,
                                                   at=at)
        if context is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Person not found"}},
            )
        return context

    @app.get("/v1/people/{person_id}/projects")
    def get_person_projects(person_id: str,
                            at: str | None = Query(default=None)):
        person = org_structure.get_person(_store(app), person_id)
        if person is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Person not found"}},
            )
        return {"projects": org_structure.get_person_projects(
            _store(app), person_id, at=at)}

    @app.get("/v1/projects/{project_id}/team")
    def get_project_team(project_id: str,
                         at: str | None = Query(default=None)):
        team = org_structure.get_project_team(_store(app), project_id, at=at)
        if team is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Project not found"}},
            )
        return team

    # --- Phase 04: Personal Assistant ---

    @app.post("/v1/assistants", status_code=201)
    def post_assistant(body: AssistantCreate):
        try:
            return assistant_service.create_assistant(
                _store(app), kind=body.kind, name=body.name,
                owner_person_id=body.owner_person_id,
                department_id=body.department_id,
                project_id=body.project_id,
            )
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except ValueError as exc:
            code = 409 if "already exists" in str(exc) else 422
            return JSONResponse(status_code=code, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.get("/v1/assistants/{assistant_id}")
    def get_assistant(assistant_id: str):
        try:
            return assistant_service.resolve_assistant_context(
                _store(app), assistant_id)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except (ValueError, AuthorizationError) as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.post("/v1/assistants/{assistant_id}/chat")
    def post_chat(assistant_id: str, body: ChatRequest,
                  x_api_key: str | None = Header(default=None)):
        identity = _authenticate(x_api_key)
        if isinstance(identity, JSONResponse):
            return identity
        limited = _rate_limit(identity)
        if limited is not None:
            return limited
        try:
            return assistant_service.chat(
                _store(app), assistant_id, body.actor_person_id, body.message,
                current_project_id=body.current_project_id,
                adapters=app.state.adapters,
            )
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})
        except ValueError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.get("/v1/people/{person_id}/tasks")
    def get_person_tasks(person_id: str,
                         status: str | None = Query(default=None)):
        person = org_structure.get_person(_store(app), person_id)
        if person is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found",
                                   "message": "Person not found"}},
            )
        sql = ("SELECT * FROM tasks WHERE assignee_person_id = ?"
               " AND is_deleted = 0")
        params: tuple = (person_id,)
        if status is not None:
            sql += " AND status = ?"
            params = (person_id, status)
        rows = _store(app).query_all(sql + " ORDER BY created_at", params)
        return {"tasks": [dict(r) for r in rows]}

    # --- Phase 05: Department Agents ---

    @app.get("/v1/department-agents")
    def list_department_agents():
        return {"agents": dept_agents.ensure_department_agents(_store(app))}

    @app.get("/v1/department-agents/{dept_code}")
    def get_department_agent(dept_code: str):
        try:
            return dept_agents.get_department_agent(_store(app), dept_code)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})

    @app.post("/v1/department-agents/route")
    def route_department_agent(body: RouteRequest):
        try:
            return dept_agents.route_to_agent(
                _store(app), body.message, candidates=body.candidates)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})

    @app.post("/v1/department-agents/coordinate")
    def coordinate_agents(body: CoordinateRequest,
                          x_api_key: str | None = Header(default=None)):
        identity = _authenticate(x_api_key)
        if isinstance(identity, JSONResponse):
            return identity
        limited = _rate_limit(identity)
        if limited is not None:
            return limited
        try:
            return dept_agents.coordinate(
                _store(app), body.actor_person_id, body.message,
                agent_codes=body.agents, adapters=app.state.adapters)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})
        except ValueError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    # --- Phase 06: Project dashboard ---

    @app.get("/v1/projects")
    def list_projects():
        proj_agents.ensure_project_roles(_store(app))
        rows = _store(app).query_all(
            "SELECT * FROM projects WHERE is_deleted = 0 ORDER BY code")
        return {"projects": [dict(r) for r in rows]}

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str):
        try:
            proj_agents.ensure_project_agent(_store(app), project_id)
            return proj_agents.get_project_summary(
                _store(app), project_id)["project"]
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})

    def _project_items(project_id: str, key: str):
        try:
            summary = proj_agents.get_project_summary(_store(app), project_id)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        return {key: summary[key]}

    @app.get("/v1/projects/{project_id}/tasks")
    def get_project_tasks(project_id: str):
        return _project_items(project_id, "tasks")

    @app.get("/v1/projects/{project_id}/milestones")
    def get_project_milestones(project_id: str):
        return _project_items(project_id, "milestones")

    @app.get("/v1/projects/{project_id}/risks")
    def get_project_risks(project_id: str):
        return _project_items(project_id, "risks")

    @app.get("/v1/projects/{project_id}/issues")
    def get_project_issues(project_id: str):
        return _project_items(project_id, "issues")

    @app.get("/v1/projects/{project_id}/decisions")
    def get_project_decisions(project_id: str):
        return _project_items(project_id, "decisions")

    @app.get("/v1/projects/{project_id}/summary")
    def get_project_summary(project_id: str):
        try:
            return proj_agents.project_brief(_store(app), project_id,
                                             adapters=app.state.adapters)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})

    # --- Phase 07: Workflow / Task / Approval (HITL) ---

    @app.post("/v1/workflows", status_code=201)
    def post_workflow(body: WorkflowCreate):
        return wf_service.create_workflow(_store(app), body.code, body.name,
                                          body.definition)

    @app.get("/v1/workflows")
    def list_workflows():
        rows = _store(app).query_all(
            "SELECT * FROM workflows WHERE is_deleted = 0 ORDER BY code")
        states = {s: list(wf_service.TRANSITIONS.get(s, ()))
                  for s in wf_service.STATES}
        return {"workflows": [dict(r) for r in rows], "states": states}

    @app.post("/v1/workflow-instances", status_code=201)
    def post_instance(body: InstanceCreate):
        try:
            return wf_service.start_instance(
                _store(app), body.workflow_id, body.business_ref_type,
                body.business_ref_id)
        except Exception as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.post("/v1/workflow-instances/{instance_id}/transition")
    def post_transition(instance_id: str, body: TransitionRequest):
        try:
            return wf_service.transition_instance(
                _store(app), instance_id, body.to_state,
                body.actor_person_id)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid_transition", "message": str(exc)}})

    @app.post("/v1/tasks", status_code=201)
    def post_task(body: TaskCreate):
        try:
            return wf_service.create_task(
                _store(app), body.title, body.owner_person_id,
                body.assignee_person_id, body.department_id, body.project_id,
                body.priority, body.due_at, body.dependencies, body.source)
        except Exception as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.get("/v1/tasks")
    def list_tasks(assignee: str | None = Query(default=None),
                   project: str | None = Query(default=None),
                   status: str | None = Query(default=None)):
        sql = "SELECT * FROM tasks WHERE is_deleted = 0"
        params: list = []
        if assignee:
            sql += " AND assignee_person_id = ?"
            params.append(assignee)
        if project:
            sql += " AND project_id = ?"
            params.append(project)
        if status:
            sql += " AND status = ?"
            params.append(status)
        rows = _store(app).query_all(sql + " ORDER BY created_at",
                                     tuple(params))
        return {"tasks": [dict(r) for r in rows]}

    @app.patch("/v1/tasks/{task_id}")
    def patch_task(task_id: str, body: dict):
        try:
            return wf_service.update_task(_store(app), task_id, body)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.post("/v1/approvals", status_code=201)
    def post_approval(body: ApprovalCreate):
        try:
            return wf_service.request_approval(
                _store(app), body.requested_by, body.action, body.resource,
                body.reason, body.approver_person_id, body.approver_role_id,
                body.workflow_instance_id, body.idempotency_key,
                body.expires_at)
        except Exception as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.get("/v1/approvals")
    def list_approvals(status: str | None = Query(default=None)):
        sql = "SELECT * FROM approvals WHERE is_deleted = 0"
        params: tuple = ()
        if status:
            sql += " AND status = ?"
            params = (status,)
        rows = _store(app).query_all(sql + " ORDER BY created_at", params)
        return {"approvals": [dict(r) for r in rows]}

    @app.post("/v1/approvals/{approval_id}/decide")
    def post_decide(approval_id: str, body: DecideRequest):
        try:
            return wf_service.decide_approval(
                _store(app), approval_id, body.approver_person_id,
                body.verdict, body.reason)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.ApprovalExpired as exc:
            return JSONResponse(status_code=410, content={
                "error": {"code": "expired", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.post("/v1/approvals/{approval_id}/escalate")
    def post_escalate(approval_id: str, body: EscalateRequest):
        try:
            return wf_service.escalate_approval(
                _store(app), approval_id, body.by_person_id,
                body.to_person_id, body.to_role_id, body.reason)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    @app.post("/v1/approvals/{approval_id}/execute")
    def post_execute(approval_id: str, body: ExecuteRequest):
        try:
            return wf_service.execute_consequential(
                _store(app), approval_id, body.executor_person_id,
                adapters=app.state.adapters)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    # --- Phase 09: Internal Agent execution layer ---

    @app.post("/v1/executions", status_code=201)
    def post_execution(body: DispatchRequest,
                       x_api_key: str | None = Header(default=None)):
        identity = _authenticate(x_api_key)
        if isinstance(identity, JSONResponse):
            return identity
        limited = _rate_limit(identity)
        if limited is not None:
            return limited
        try:
            record, duplicate = exec_service.submit_execution(
                _store(app), app.state.adapters.internal_agent,
                body.actor_person_id, body.action, body.resource, body.task,
                body.project_id, body.department_id, body.idempotency_key,
                body.extra)
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})
        except CoreClientError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden",
                          "message": exc.message}})
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        if record.get("failed"):
            return JSONResponse(status_code=502, content={
                "error": {"code": "execution_failed",
                          "message": record.get("error", "")},
                "execution": record})
        if duplicate:
            return JSONResponse(status_code=200, content={
                "execution": record, "duplicate": True})
        return {"execution": record, "duplicate": False}

    @app.get("/v1/executions/{execution_id}")
    def get_execution(execution_id: str):
        try:
            return exec_service.poll_execution(
                _store(app), app.state.adapters.internal_agent, execution_id)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})

    @app.post("/v1/executions/{execution_id}/cancel")
    def cancel_execution(execution_id: str, body: CancelExecutionRequest):
        try:
            return exec_service.cancel_execution(
                _store(app), app.state.adapters.internal_agent,
                execution_id, body.actor_person_id)
        except LookupError as exc:
            return JSONResponse(status_code=404, content={
                "error": {"code": "not_found", "message": str(exc)}})
        except wf_service.WorkflowError as exc:
            return JSONResponse(status_code=422, content={
                "error": {"code": "invalid", "message": str(exc)}})

    # --- Phase 10: Enterprise Agent ---

    def _ent(view, actor_person_id: str):
        try:
            return view(_store(app), actor_person_id)
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})

    @app.get("/v1/enterprise/overview")
    def ent_overview(actor_person_id: str = Query()):
        return _ent(ent_service.company_overview, actor_person_id)

    @app.get("/v1/enterprise/departments/health")
    def ent_health(actor_person_id: str = Query()):
        return _ent(ent_service.department_health, actor_person_id)

    @app.get("/v1/enterprise/projects/portfolio")
    def ent_portfolio(actor_person_id: str = Query()):
        return _ent(ent_service.project_portfolio, actor_person_id)

    @app.get("/v1/enterprise/risks")
    def ent_risks(actor_person_id: str = Query()):
        return _ent(ent_service.risk_overview, actor_person_id)

    @app.get("/v1/enterprise/issues")
    def ent_issues(actor_person_id: str = Query()):
        return _ent(ent_service.issue_overview, actor_person_id)

    @app.get("/v1/enterprise/approvals")
    def ent_approvals(actor_person_id: str = Query()):
        return _ent(ent_service.pending_approvals, actor_person_id)

    @app.get("/v1/enterprise/resources")
    def ent_resources(actor_person_id: str = Query()):
        return _ent(ent_service.resource_overview, actor_person_id)

    @app.post("/v1/enterprise/brief")
    def ent_brief(body: BriefRequest,
                  x_api_key: str | None = Header(default=None)):
        identity = _authenticate(x_api_key)
        if isinstance(identity, JSONResponse):
            return identity
        try:
            return ent_service.executive_brief(
                _store(app), body.actor_person_id,
                adapters=app.state.adapters)
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})

    @app.post("/v1/enterprise/act")
    def ent_act(body: EnterpriseActRequest,
                x_api_key: str | None = Header(default=None)):
        identity = _authenticate(x_api_key)
        if isinstance(identity, JSONResponse):
            return identity
        try:
            result = ent_service.enterprise_act(
                _store(app), body.actor_person_id, body.verb, body.action,
                body.resource, body.context)
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden", "message": str(exc)}})
        if not result["allowed"]:
            return JSONResponse(status_code=403, content={
                "error": {"code": "forbidden",
                          "message": result.get("reason", "")},
                "result": result})
        return result

    return app
