# LONGTHINK ORGANIZATION CORE

Independent core of the LongThink enterprise AI ecosystem (Phase 01–12).
Answers **WHO / WHERE / WHAT ROLE / WHAT AUTHORITY / WHICH PROJECT /
WHICH WORKFLOW / WHO APPROVES**. Never touches Knowledge/Intelligence
databases — contact only through adapters.

## Architecture

```text
Human (owns authority)
  └─ Personal Assistant (1 per person) ─┬─ Department Agents (7)
                                        ├─ Project Agents (per project)
                                        └─ Enterprise Agent (company-wide)
Organization Core: actor / context / role / authority / routing
  ├─ Intelligence Core (ASK/PLAN/EXECUTE/EVALUATE) via HttpIntelligenceAdapter
  ├─ Knowledge Core (SEARCH/RETRIEVE/CITE/...) via HttpKnowledgeAdapter
  └─ Internal Agent (execution) via envelope + agent_executions ledger
```

Modules: `models` `store` `seed` `auth` (RBAC/ABAC) `org_structure`
`assistant` `department_agents` `project_agents` `workflows` (HITL)
`execution` `enterprise` `adapters`+`integration` `governance`
`observability` `api` (FastAPI) | `migrations/0001..0007` | `tests/`

## Setup

```powershell
# venv already exists at FirstSecondBrain\.venv (repo convention)
python -m pytest organization_core/tests/ -q
python -m ruff check organization_core
# run standalone API on :8101
$env:ORGANIZATION_CORE_PORT = "8101"
python -m organization_core.service
curl http://127.0.0.1:8101/health   # {"status":"ok"}
curl http://127.0.0.1:8101/ready    # readiness + schema checks
```

Docker: `docker compose -f organization_core/docker-compose.yml up --build`

## Env

See `.env.example`. Keys: `ORGANIZATION_CORE_{HOST,PORT,DB,API_KEYS,
RATE_LIMIT_PER_MINUTE}` + `ORGANIZATION_CORE_{KNOWLEDGE,INTELLIGENCE}_{URL,
API_KEY,TIMEOUT_SECONDS,MAX_RETRIES}`. Empty core URLs = mock adapters.

## API (prefix /v1, FastAPI — stack convention)

Org/structure: `organization departments departments/{id} people/{id}[/
context|projects|tasks] versions` · Assistants: `assistants[POST]/{id}[chat]`
· Dept agents: `department-agents[/route/coordinate]` · Projects:
`projects[/{id}/team|tasks|milestones|risks|issues|decisions|summary]` ·
Workflow: `workflows workflow-instances[/transition] tasks approvals[/
decide|escalate|execute]` · Executions: `executions[/{id}[/cancel]]` ·
Enterprise: `enterprise/{overview|departments/health|projects/portfolio|
risks|issues|approvals|resources}[/brief|act]` · Ops: `/health /ready
/v1/metrics`.

## Adapters

Ports in `adapters.py` (mock default). `integration.py` maps to CONFIRMED
repo endpoints only: `POST /v1/memory/search`, `GET /v1/memory/{id}`,
`POST /v1/mid-brain/{knowledge,process,plan,execute}` (+timeout/retry/
circuit-breaker/correlation-id). No endpoint is guessed: `feedback()` has
no real endpoint and reports `recorded:false`; `evaluate()` reuses
`/process` (documented). Outbound context is minimal
(actor/org/dept/project/role/permissions/correlation) — never secrets.
Internal Agent = in-process `FirstBrainAgent.run` bridge (opt-in `local`).

## Seed

`seed_dak()`: Company DAK + BGD + 7 departments (TCHC/TCKT/KTHD/KTGS/PTDA/
TKCN/AT) + 52 position templates (baseline, NOT headcount) + org version
`v2026.01`. Idempotent. No real personal names.

## Test

```powershell
python -m pytest organization_core/tests/ -q   # 140+ tests, all layers
python -m pytest -q                            # repo regression (untouched)
```

Layers: unit/domain/repository/API/RBAC-ABAC/workflow/agent/integration/
E2E (`test_e2e.py`)/security (`test_governance_audit.py`, 8 attack classes).
`pytest.ini testpaths` intentionally unchanged (repo convention: satellite
suites run explicitly, like `mid_brain/tests/`).

## Deployment

`Dockerfile` (py3.12-slim, :8101, HEALTHCHECK /health),
`docker-compose.yml` (own volume, env_file), `.env.example`.
Production: set `ORGANIZATION_CORE_API_KEYS`, rate limit, core URLs+keys.

## Security assumptions

Deny-by-default RBAC/ABAC + HITL for consequential actions; agents never
self-grant; hash-chained append-only audit (`verify_audit_chain`);
versioned policies; tenant isolation (DAK); prompt-injection boundary
(retrieved = DATA, POLICY only from policies table); tool allowlists;
PII minimization; secrets via env, redacted from logs; open-mode auth is
DEV ONLY.
