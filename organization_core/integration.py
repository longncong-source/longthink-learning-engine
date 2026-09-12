"""LONGTHINK ORGANIZATION CORE — Phase 08 core integration (HTTP, read-only).

Organization Core NEVER touches other cores' databases. All contact goes
through these adapters.

Confirmed endpoint map (read from the repo, NOT guessed):
- Knowledge Core (Second Brain cloud API, ``X-API-Key`` auth):
    POST {base}/v1/memory/search   {query, project_id?, top_k?, filters?}
    GET  {base}/v1/memory/{id}
    POST {base}/v1/mid-brain/knowledge {content, kind?, project_id?}
      (knowledge-write path confirmed in cloud/app/routers/mid_brain.py)
- Intelligence Core (Mid Brain routes in cloud/app/routers/mid_brain.py):
    POST {base}/v1/mid-brain/process  {question, project_id?, context}
    POST {base}/v1/mid-brain/plan     {goal, project_id?, context}
    POST {base}/v1/mid-brain/execute  {plan_id, approved_task_ids?}
  (No dedicated evaluate endpoint exists, so evaluate() is served through
  /process with an evaluation-framed question — documented, not guessed.)

Resilience: per-request timeout, retry with exponential backoff (transient
failures only), per-adapter circuit breaker, correlation_id/request_id on
every call, structured CoreClientError. Secrets come from env only.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

import httpx

from organization_core.adapters import (
    AdapterBundle,
    IntelligencePort,
    InternalAgentPort,
    KnowledgePort,
    MockIntelligenceAdapter,
    MockInternalAgentAdapter,
    MockKnowledgeAdapter,
)
from organization_core.observability import timed as obs_timed
from organization_core.store import OrganizationStore

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@dataclass(slots=True)
class CoreClientError(Exception):
    code: str  # timeout | connection | http | invalid_response | circuit_open
    message: str
    correlation_id: str
    status: int | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message,
                "correlation_id": self.correlation_id, "status": self.status}


@dataclass(slots=True)
class CoreClientConfig:
    base_url: str = "http://127.0.0.1:8100"
    api_key: str = ""
    timeout_seconds: float = 10.0
    max_retries: int = 2
    backoff_base_seconds: float = 0.2
    circuit_threshold: int = 3
    circuit_cooldown_seconds: float = 30.0
    transport: httpx.BaseTransport | None = None  # tests only, never env

    @classmethod
    def from_env(cls, prefix: str,
                 default_url: str = "http://127.0.0.1:8100") -> CoreClientConfig:
        return cls(
            base_url=os.environ.get(f"{prefix}_URL", default_url),
            api_key=os.environ.get(f"{prefix}_API_KEY", ""),
            timeout_seconds=float(
                os.environ.get(f"{prefix}_TIMEOUT_SECONDS", "10")),
            max_retries=int(os.environ.get(f"{prefix}_MAX_RETRIES", "2")),
        )


class CircuitBreaker:
    """closed -> open (after N consecutive failures) -> half-open probe."""

    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if time.monotonic() - self.opened_at >= self.cooldown:
            return "half-open"
        return "open"

    def before_call(self, correlation_id: str) -> None:
        if self.state == "open":
            raise CoreClientError("circuit_open",
                                  "circuit breaker is open", correlation_id)

    def after_call(self, ok: bool) -> None:
        if ok:
            self.failures = 0
            self.opened_at = None
        else:
            self.failures += 1
            if self.state == "half-open" or self.failures >= self.threshold:
                self.opened_at = time.monotonic()


class ResilientHttpClient:
    def __init__(self, config: CoreClientConfig, name: str) -> None:
        self.config = config
        self.name = name
        self.breaker = CircuitBreaker(config.circuit_threshold,
                                      config.circuit_cooldown_seconds)
        self._client: httpx.Client | None = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                transport=self.config.transport,
            )
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def call(self, method: str, path: str, payload: dict | None,
             correlation_id: str) -> dict:
        self.breaker.before_call(correlation_id)
        with obs_timed("org_external_core_latency_seconds",
                       {"core": self.name}):
            return self._call_inner(method, path, payload, correlation_id)

    def _call_inner(self, method: str, path: str, payload: dict | None,
                    correlation_id: str) -> dict:
        headers = {
            "X-Correlation-ID": correlation_id,
            "X-Request-ID": correlation_id,
        }
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        attempts = 0
        last_error: CoreClientError | None = None
        while attempts <= self.config.max_retries:
            attempts += 1
            try:
                response = self._http().request(
                    method, path, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                last_error = CoreClientError(
                    "timeout", f"{self.name} timeout: {exc}", correlation_id)
            except httpx.TransportError as exc:
                last_error = CoreClientError(
                    "connection", f"{self.name} connection: {exc}",
                    correlation_id)
            else:
                if response.status_code in RETRYABLE_STATUS:
                    last_error = CoreClientError(
                        "http", f"{self.name} HTTP {response.status_code}",
                        correlation_id, status=response.status_code)
                elif response.status_code >= 400:
                    self.breaker.after_call(False)
                    raise CoreClientError(
                        "http", f"{self.name} HTTP {response.status_code}",
                        correlation_id, status=response.status_code)
                else:
                    try:
                        data = response.json()
                    except ValueError:
                        self.breaker.after_call(False)
                        raise CoreClientError(
                            "invalid_response",
                            f"{self.name} returned non-JSON", correlation_id,
                            status=response.status_code) from None
                    if not isinstance(data, dict):
                        self.breaker.after_call(False)
                        raise CoreClientError(
                            "invalid_response",
                            f"{self.name} returned non-object JSON",
                            correlation_id, status=response.status_code)
                    self.breaker.after_call(True)
                    return data
            if attempts <= self.config.max_retries:
                time.sleep(self.config.backoff_base_seconds * (2 ** (attempts - 1)))
        self.breaker.after_call(False)
        raise last_error or CoreClientError("http", "unknown failure",
                                            correlation_id)


def build_outbound_context(
    store: OrganizationStore,
    actor_person_id: str,
    project_id: str | None = None,
    department_id: str | None = None,
    correlation_id: str | None = None,
) -> dict:
    """Minimal outbound context. No names, contents, or secrets — ever."""
    person = store.query_one(
        "SELECT id FROM persons WHERE id = ? AND status = 'active'"
        " AND is_deleted = 0",
        (actor_person_id,),
    )
    if person is None:
        raise CoreClientError("http", "unknown or inactive actor",
                              correlation_id or new_correlation_id())
    company = store.query_one(
        "SELECT id FROM companies WHERE code = 'DAK' AND is_deleted = 0")
    roles = [r["code"] for r in store.query_all(
        "SELECT r.code AS code FROM person_roles pr "
        "JOIN roles r ON r.id = pr.role_id AND r.is_deleted = 0 "
        "WHERE pr.person_id = ? AND pr.is_deleted = 0", (actor_person_id,))]
    permissions = [f"{r['action']}:{r['resource']}" for r in store.query_all(
        "SELECT p.action AS action, p.resource AS resource"
        " FROM person_roles pr JOIN roles r ON r.id = pr.role_id"
        " AND r.is_deleted = 0 JOIN role_permissions rp ON rp.role_id = r.id"
        " JOIN permissions p ON p.id = rp.permission_id AND p.is_deleted = 0"
        " WHERE pr.person_id = ? AND pr.is_deleted = 0", (actor_person_id,))]
    if department_id is None:
        seat = store.query_one(
            "SELECT pos.department_id AS department_id FROM person_positions pp"
            " JOIN positions pos ON pos.id = pp.position_id"
            " WHERE pp.person_id = ? AND pp.is_deleted = 0"
            " ORDER BY pp.is_primary DESC LIMIT 1",
            (actor_person_id,),
        )
        department_id = seat["department_id"] if seat else None
    return {
        "actor_id": actor_person_id,
        "organization_id": company["id"] if company else None,
        "department_id": department_id,
        "project_id": project_id,
        "role": sorted(set(roles)),
        "permissions": sorted(set(permissions)),
        "correlation_id": correlation_id or new_correlation_id(),
    }


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def _require_list(data: dict, key: str, adapter: str,
                  correlation_id: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise CoreClientError(
            "invalid_response",
            f"{adapter} response missing list field {key!r}", correlation_id)
    return value


class HttpKnowledgeAdapter(KnowledgePort):
    def __init__(self, client: ResilientHttpClient) -> None:
        self.client = client

    def search(self, query: str, context: dict) -> dict:
        cid = new_correlation_id()
        data = self.client.call("POST", "/v1/memory/search", {
            "query": query,
            "project_id": context.get("project_id"),
            "top_k": context.get("top_k", 8),
            "filters": context.get("filters", {}),
            "context": _safe_context(context),
        }, cid)
        results = _require_list(data, "results", "knowledge", cid)
        return {
            "backend": "http",
            "total": data.get("total", len(results)),
            "results": [{
                "ref_id": str(r.get("id", "")),
                "title": r.get("title", ""),
                "snippet": str(r.get("content", ""))[:200],
                "score": r.get("score"),
            } for r in results if isinstance(r, dict)],
        }

    def retrieve(self, ref_id: str) -> dict:
        cid = new_correlation_id()
        data = self.client.call("GET", f"/v1/memory/{ref_id}", None, cid)
        if "content" not in data and "title" not in data:
            raise CoreClientError("invalid_response",
                                  "knowledge retrieve missing content", cid)
        return {"backend": "http", "ref_id": ref_id,
                "title": data.get("title"), "content": data.get("content")}

    def cite(self, ref_id: str) -> dict:
        item = self.retrieve(ref_id)
        title = item.get("title") or ref_id
        return {"backend": "http", "ref_id": ref_id,
                "citation": f"{title} [knowledge:{ref_id}]"}

    def feedback(self, ref_id: str, useful: bool) -> dict:
        # No feedback endpoint exists in the confirmed Knowledge surface.
        return {"backend": "http", "ref_id": ref_id, "recorded": False,
                "useful": useful,
                "reason": "no feedback endpoint; report via audit instead"}

    def knowledge_candidate(self, draft: dict) -> dict:
        cid = new_correlation_id()
        data = self.client.call("POST", "/v1/mid-brain/knowledge", {
            "content": str(draft.get("content", ""))[:10000],
            "kind": draft.get("kind"),
            "project_id": draft.get("project_id"),
            "source": "organization-core",
        }, cid)
        if "knowledge_id" not in data:
            raise CoreClientError("invalid_response",
                                  "knowledge store missing knowledge_id", cid)
        return {"backend": "http", "accepted": True,
                "knowledge_id": data["knowledge_id"]}


class HttpIntelligenceAdapter(IntelligencePort):
    def __init__(self, client: ResilientHttpClient) -> None:
        self.client = client

    def ask(self, question: str, context: dict) -> dict:
        cid = new_correlation_id()
        data = self.client.call("POST", "/v1/mid-brain/process", {
            "question": question,
            "project_id": context.get("project_id"),
            "context": _safe_context(context),
        }, cid)
        if "answer" not in data:
            raise CoreClientError("invalid_response",
                                  "intelligence ask missing answer", cid)
        return {"backend": "http", "answer": data["answer"],
                "confidence": data.get("confidence", 0.0),
                "trace_id": data.get("trace_id")}

    def plan(self, goal: str, context: dict) -> dict:
        cid = new_correlation_id()
        data = self.client.call("POST", "/v1/mid-brain/plan", {
            "goal": goal,
            "project_id": context.get("project_id"),
            "context": _safe_context(context),
        }, cid)
        if "plan_id" not in data and "steps" not in data:
            raise CoreClientError("invalid_response",
                                  "intelligence plan missing plan_id", cid)
        return {"backend": "http", **data}

    def execute(self, plan_id: str, context: dict) -> dict:
        cid = new_correlation_id()
        data = self.client.call("POST", "/v1/mid-brain/execute", {
            "plan_id": plan_id,
            "approved_task_ids": context.get("approved_task_ids", []),
        }, cid)
        if "results" not in data:
            raise CoreClientError("invalid_response",
                                  "intelligence execute missing results", cid)
        return {"backend": "http", **data}

    def evaluate(self, result: dict, context: dict) -> dict:
        # No dedicated endpoint: served through /process (documented above).
        asked = self.ask(
            "Evaluate this outcome and score alternatives: "
            + str(result)[:1000], context)
        return {"backend": "http", "evaluation": asked["answer"],
                "confidence": asked.get("confidence", 0.0)}


def _safe_context(context: dict) -> dict:
    """Strip anything but the minimal propagation fields before sending out."""
    allowed = {"actor_id", "organization_id", "department_id", "project_id",
               "role", "permissions", "correlation_id", "project_code",
               "company", "person"}
    person = context.get("person")
    safe = {k: v for k, v in context.items() if k in allowed}
    if isinstance(person, dict):
        safe["person"] = {"code": person.get("code")}
    elif person is not None:
        safe["person"] = {"code": str(person)}
    return safe


@dataclass(slots=True)
class IntegrationBundle:
    knowledge: KnowledgePort
    intelligence: IntelligencePort
    internal_agent: InternalAgentPort
    knowledge_client: ResilientHttpClient | None = None
    intelligence_client: ResilientHttpClient | None = None

    def close(self) -> None:
        if self.knowledge_client:
            self.knowledge_client.close()
        if self.intelligence_client:
            self.intelligence_client.close()

    def to_adapters(self) -> AdapterBundle:
        return AdapterBundle(knowledge=self.knowledge,
                             intelligence=self.intelligence,
                             internal_agent=self.internal_agent)


def build_integration(
    knowledge_cfg: CoreClientConfig | None = None,
    intelligence_cfg: CoreClientConfig | None = None,
) -> IntegrationBundle:
    """HTTP adapters when a base URL is configured, mocks otherwise."""
    if knowledge_cfg is None:
        knowledge_cfg = CoreClientConfig.from_env("ORGANIZATION_CORE_KNOWLEDGE",
                                                  "")
    if intelligence_cfg is None:
        intelligence_cfg = CoreClientConfig.from_env(
            "ORGANIZATION_CORE_INTELLIGENCE", "")
    if knowledge_cfg.base_url:
        knowledge_client: ResilientHttpClient | None = ResilientHttpClient(
            knowledge_cfg, "knowledge")
        knowledge: KnowledgePort = HttpKnowledgeAdapter(knowledge_client)
    else:
        knowledge_client = None
        knowledge = MockKnowledgeAdapter()
    if intelligence_cfg.base_url:
        intelligence_client: ResilientHttpClient | None = ResilientHttpClient(
            intelligence_cfg, "intelligence")
        intelligence: IntelligencePort = HttpIntelligenceAdapter(
            intelligence_client)
    else:
        intelligence_client = None
        intelligence = MockIntelligenceAdapter()
    return IntegrationBundle(
        knowledge=knowledge, intelligence=intelligence,
        internal_agent=MockInternalAgentAdapter(),
        knowledge_client=knowledge_client,
        intelligence_client=intelligence_client)


def adapters_from_env() -> AdapterBundle:
    """App wiring: real HTTP adapters only when env configures them."""
    return build_integration().to_adapters()
