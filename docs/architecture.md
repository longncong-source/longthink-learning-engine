# Architecture - LongThink Learning Engine (First Brain + Second Brain)

## MVP stack (5 components, per project directive)

| Component | Role | Where |
|---|---|---|
| OpenCode | agent runtime / developer interface | local |
| Ollama / LM Studio | local LLM (+ embeddings), provider configurable | local |
| FastAPI | Second Brain Memory API (`cloud/`) | local container or bare |
| PostgreSQL + pgvector | long-term memory store | `docker-compose.brain.yml` |
| Docker Compose | orchestration of db+api | root |

**Dev fallback:** when Docker is unavailable the API runs with
`MEMORY_DB_BACKEND=sqlite` (same repository interface), so the complete loop works
on any laptop. Switching backends is one env var.

## Component diagram

```
┌──────────────────────────────┐         ┌───────────────────────────────┐
│ FIRST BRAIN (local/)         │         │ SECOND BRAIN (cloud/)         │
│                              │         │                               │
│ brain_cli  ─ demo ─ agent.py │  HTTPS  │ FastAPI Memory API (:8100)    │
│ memory_client (cache+queue)  │────────▶│  ├ auth (API key, rate limit) │
│ local_store.sqlite           │  REST   │  ├ redaction filter           │
│   ├ session notes            │         │  ├ hybrid search service      │
│   ├ pending_writes (outbox)  │◀────────│  └ embeddings (hash/ollama/   │
│ llm.py (ollama/lmstudio/echo)│ results │     openai_compatible)        │
└──────────────────────────────┘         │ PostgreSQL+pgvector :5433     │
                                         │   or SQLite fallback          │
        legacy RAG stack (app/, Qdrant, WebUI) runs untouched alongside │
└─────────────────────────────────────────────────────────────────────────┘
```

## The loop (spec §17)

`OBSERVE → RETRIEVE → THINK → PLAN → EXECUTE → VERIFY → REFLECT → STORE`

implemented in `local/agent.py::FirstBrainAgent.run()`:

- **RETRIEVE** never dumps the database; top-k hybrid search only (§11).
- **THINK/EXECUTE** treat retrieved memories as *evidence/data*, framed as
  untrusted in every prompt (§33/34).
- **REFLECT** uses deterministic classifiers (`classify_memory`,
  `is_long_term_worthy`) - not the LLM - to decide storage (§12/13).
- **STORE** goes through client redaction + DATA_POLICY gate; failures are
  queued in SQLite and flushed by `brain sync` (§20/23).

## Data flow contracts

- Write pipeline (§10): validate → redact → verify project → embed → dedupe
  (cosine ≥ threshold ⇒ merge/update) → store.
- Search scoring (§9):
  `final = w_sem·semantic + w_kw·keyword + w_imp·importance + w_rec·recency`
  weights configurable (`WEIGHT_*`), normalized to sum 1.0.
  - semantic: pgvector cosine `<=>` (PG) or pure-python cosine (SQLite)
  - keyword: term F1 overlap (both backends; PG keeps a GIN tsvector for future)
  - recency: exponential decay `0.5^(age_days/half_life)`
- Health contract (§8): `GET /health` returns exactly `{"status": "ok"}`.

## Failure modes (§23)

| Failure | Behaviour |
|---|---|
| Cloud down at write | payload queued locally, `status=queued`, sync later |
| Cloud down at search | agent degrades to local reasoning, still answers |
| Auth mismatch | raises immediately, never queues (config bug) |
| Embedding server down | HTTP 503 with meaningful error body |
| DB unreachable | `/health/details` shows degraded; writes return 503 |

## Phase status

| Phase | Scope | Status |
|---|---|---|
| 1 Foundation | compose, migration, health, config | ✅ done |
| 2 Memory | schema, CRUD, embeddings, hybrid search, dedupe | ✅ done |
| 3 Local Brain | config, LLM abstraction, client, queue/cache, CLI | ✅ done |
| 4 Full Loop | agent 8 phases, human-in-loop, demo §27 | ✅ done (live run PASS) |
| 5 Documents | PDF/DOCX/MD/TXT extraction, semantic chunking, RAG via mirrored memories, cascade delete | ✅ done (live RAG run PASS) |
| 6 Security hardening | key auth, redaction, rate limit, **persistent audit trail + `/v1/admin/audit`** | ✅ done (JWT/OAuth deferred by design; static keys per MVP §21) |
| 7 Production | queue/cache/retries, **Prometheus metrics `/v1/admin/metrics`**, backup automation (`scripts/backup.*`) | ✅ done MVP (migrations auto-apply; monitoring = counters endpoint) |

Legacy Qdrant document stack (`app/`, `documents/`) remains available but is now
superseded by the built-in ingestion pipeline for new work.


Deferred by design (spec §37/38): knowledge graph, multi-agent roles, GitHub/n8n
integration - interfaces are kept open but nothing is built until the loop above
is proven stable.

## LongThink Control Center (Web Console — beyond MVP §37)

`GET /ui/` (StaticFiles at `cloud/app/ui/`, served by the same FastAPI process):

- **Obsidian-style Graph View** (`GET /v1/graph` + `/v1/graph/status`): projects ◆, memories ● (colored by type), documents ■ with force-directed layout; links `belongs_to`/`has_document`/`chunk_of`.
- **Projects tab** (`POST/GET /v1/projects`): create/list with live dropdown sync.
- **Upload** (`POST /v1/documents/upload` + `POST /v1/memory/import`): local **or** cloud target (CORS `*`), documents (RAG-chunked) vs bulk file→memory (json/jsonl/csv/md/txt, ≤1000 items, redaction+dedupe).
- **Observability**: audit `kind` (`/v1/admin/audit`) + Prometheus metrics (`/v1/admin/metrics`). UI traffic is excluded from audit.
- **Brand**: OpenAPI title `LongThink Learning Engine v1.0.0` (via `cloud/app/config.py:app_name`).
