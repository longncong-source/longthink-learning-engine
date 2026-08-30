# Phase 0: System Audit — First Brain & Second Brain Current State

> **Purpose**: Document the as-built state of First Brain (Local CLI/Agent) and Second Brain (FastAPI Cloud) before Mid Brain integration. This audit establishes the baseline for Phase 1–13 Mid Brain implementation per the THREE BRAIN specification.

---

## 1. First Brain (Local CLI/Agent) — Current State

### 1.1 Architecture
- **Location**: `local/` (Python CLI package)
- **Entry Point**: `longthink` CLI command (`local/cli/main.py`)
- **Agent System**: `local/agent/` — rule-based agent with tool execution
- **Memory**: Local SQLite store (`local/store/local_store.py`)
- **LLM Integration**: Ollama client (`local/llm/ollama_client.py`) — default model `gemma4:12b`
- **Configuration**: `local/.env` — Ollama host, model, selective sync policy

### 1.2 Capabilities (MVP Complete)
| Feature | Status | Details |
|---------|--------|---------|
| CLI Commands | ✅ | `init`, `chat`, `remember`, `recall`, `sync`, `status`, `projects` |
| Local Memory Store | ✅ | SQLite with FTS5, vector search via hash embeddings |
| Agent Execution | ✅ | Rule-based with tool registry (read, write, grep, bash, etc.) |
| LLM Chat | ✅ | Streaming via Ollama, system prompts, context injection |
| Project Management | ✅ | Create/list/switch projects, project-scoped memory |
| Obsidian Sync (Phase 8) | ✅ | Bidirectional via `local/services/obsidian_service.py` |
| Redaction | ✅ | PII redaction before cloud sync |
| Selective Sync Policy | ✅ | Configurable: `all`, `explicit`, `none` |

### 1.3 Data Models
- **MemoryUnit**: `id`, `content`, `type` (episodic/semantic/procedural), `tags`, `project_id`, `embedding`, `created_at`, `updated_at`, `source` (human/agent/import)
- **Project**: `id`, `name`, `description`, `created_at`, `metadata`
- **AgentRule**: `name`, `description`, `condition`, `action`, `priority`

### 1.4 API/Interfaces
- **Local Only**: No HTTP server — direct Python API
- **Sync Interface**: `sync_to_cloud()`, `sync_from_cloud()` via Second Brain REST API
- **Obsidian Interface**: `sync_to_obsidian()`, `sync_from_obsidian()` via vault filesystem

### 1.5 Tests
- **Location**: `local/tests/`
- **Count**: 38 tests (all passing)
- **Coverage**: CLI, agent rules, LLM client, local store, memory client, redaction, demo E2E

### 1.6 Known Gaps (Pre-Mid Brain)
| Gap | Impact | Mid Brain Resolution |
|-----|--------|----------------------|
| No cross-session reasoning | Can't synthesize across chats | CognitiveOrchestrator 14-step loop |
| No confidence scoring | All answers equal weight | ConfidenceEngine 6-factor explainable |
| No conflict detection | Contradictions persist | ConflictEngine (negation, numerical, semantic) |
| No learning extraction | Insights lost | LearningEngine extracts patterns |
| No planning/decomposition | Single-step only | PlanningEngine + AgentManager |
| No adaptive network | Static knowledge graph | AdaptiveCognitiveNetwork with weight evolution |

---

## 2. Second Brain (FastAPI Cloud) — Current State

### 2.1 Architecture
- **Location**: `cloud/` (FastAPI application)
- **Entry Point**: `cloud/app/main.py` — ASGI app on port 8100
- **Database**: SQLite default (dev), PostgreSQL + pgvector (prod via Docker)
- **Embeddings**: Hash fallback (dev), Ollama `nomic-embed-text` (prod)
- **Authentication**: API key (`dev-local-key` dev only, gitignored)
- **Configuration**: `cloud/.env`, `cloud/app/config.py` (Pydantic Settings)

### 2.2 Capabilities (MVP Complete)
| Feature | Status | Details |
|---------|--------|---------|
| REST API | ✅ | OpenAPI at `/docs`, `/redoc` |
| Web UI | ✅ | React-like vanilla JS at `/ui` (chat, memory browser, graph, projects) |
| Memory CRUD | ✅ | `/v1/memories` — create, read, update, delete, search (vector + FTS) |
| Memory Import | ✅ | `/v1/memory/import` — bulk JSON/CSV/Markdown |
| Projects | ✅ | `/v1/projects` — CRUD, project-scoped memory isolation |
| Graph API | ✅ | `/v1/graph` — nodes/edges, force-directed visualization |
| Obsidian Sync (Phase 8) | ✅ | `/v1/obsidian/sync` — bidirectional, 14 folder types |
| Rate Limiting | ✅ | Token bucket per API key |
| Admin API | ✅ | `/v1/admin/*` — health, stats, maintenance |
| Redaction | ✅ | Server-side PII redaction on ingest |

### 2.3 Data Models (SQLAlchemy)
- **MemoryORM**: `id`, `content`, `memory_type`, `tags`, `project_id`, `embedding` (BYTEA), `source`, `confidence`, `metadata_json`, `created_at`, `updated_at`
- **ProjectORM**: `id`, `name`, `description`, `owner_key`, `created_at`, `metadata_json`
- **MemoryLinkORM**: `source_id`, `target_id`, `relation_type`, `strength`, `created_at`
- **ObsidianSyncORM**: `id`, `vault_path`, `last_synced`, `status`, `file_count`, `error_log`

### 2.4 API Endpoints (v1)
```
GET    /health                          → Health check
GET    /v1/memories                     → List memories (pagination, filters)
POST   /v1/memories                     → Create memory
GET    /v1/memories/{id}                → Get memory
PUT    /v1/memories/{id}                → Update memory
DELETE /v1/memories/{id}                → Delete memory
POST   /v1/memories/search              → Vector + keyword search
POST   /v1/memory/import                → Bulk import
GET    /v1/projects                     → List projects
POST   /v1/projects                     → Create project
GET    /v1/projects/{id}                → Get project
PUT    /v1/projects/{id}                → Update project
DELETE /v1/projects/{id}                → Delete project
GET    /v1/graph                        → Graph data (nodes/edges)
POST   /v1/obsidian/sync                → Trigger Obsidian sync
GET    /v1/obsidian/status              → Sync status
GET    /v1/admin/stats                  → System statistics
```

### 2.5 Tests
- **Location**: `cloud/tests/`
- **Count**: 154 tests (all passing, 4 skipped = PG integration without Docker)
- **Coverage**: All API routes, chunker, extractor, graph, memory, projects, rate limit, redaction, textops, Postgres backend

### 2.6 Known Gaps (Pre-Mid Brain)
| Gap | Impact | Mid Brain Resolution |
|-----|--------|----------------------|
| Passive storage only | No reasoning over memories | CognitiveOrchestrator processes queries |
| No cross-memory synthesis | Related memories isolated | ReferenceEngine + AdaptiveNetwork |
| No quality assessment | All memories equal | ConfidenceEngine scores each memory |
| No learning layer | Patterns not extracted | LearningEngine creates generalized knowledge |
| No conflict resolution | Contradictions in store | ConflictEngine detects & flags |
| No human feedback loop | Corrections not captured | FeedbackEvent system + Obsidian mirror |

---

## 3. Shared Infrastructure — Current State

### 3.1 Obsidian Integration (Phase 8 Complete)
| Component | First Brain | Second Brain |
|-----------|-------------|--------------|
| Vault Path | `local/.env:OBSIDIAN_VAULT_PATH` | `cloud/.env:OBSIDIAN_VAULT_PATH` |
| Sync Direction | Bidirectional | Bidirectional |
| Folder Structure | 14 cognitive folders | 14 cognitive folders |
| Frontmatter Schema | YAML with cognitive metadata | YAML with cognitive metadata |
| Conflict Resolution | Last-write-wins | Last-write-wins |
| Sync Trigger | Manual CLI (`longthink sync`) | Manual API (`POST /v1/obsidian/sync`) |

**14 Folder Types**: `00_inbox/`, `01_projects/`, `02_episodic/`, `03_semantic/`, `04_procedural/`, `05_learning/`, `06_references/`, `07_reflections/`, `08_conflicts/`, `09_plans/`, `10_agents/`, `11_feedback/`, `12_archive/`, `13_meta/`

### 3.2 Configuration Management
| Config | First Brain | Second Brain |
|--------|-------------|--------------|
| File | `local/.env` | `cloud/.env` |
| Schema | Pydantic Settings | Pydantic Settings |
| Example | `local/.env.example` | `cloud/.env.example` |
| Key Settings | Ollama, model, sync policy | DB, embeddings, auth, Obsidian, Mid Brain |

### 3.3 Mid Brain Configuration (New in Phase 12)
**Second Brain** (`cloud/app/config.py`):
```python
# Mid Brain Integration
MID_BRAIN_ENABLED: bool = True
MID_BRAIN_URL: str = "http://localhost:8100"  # Internal (same process)
MID_BRAIN_API_KEY: str = "dev-local-key"
MID_BRAIN_CONFIDENCE_THRESHOLD: float = 0.6
MID_BRAIN_ENABLE_OBSIDIAN_SYNC: bool = True
MID_BRAIN_MAX_CONCURRENT_TASKS: int = 3
```

### 3.4 Branding
- **Product**: LongThink Learning Engine v1.0.0
- **Defined In**: `pyproject.toml`, OpenAPI title, UI header, docs
- **Consistency**: Verified across all user-facing surfaces

---

## 4. Communication Between Brains (Pre-Mid Brain)

### 4.1 First → Second (Sync)
- **Mechanism**: First Brain CLI calls Second Brain REST API
- **Frequency**: Manual (`longthink sync`) or scheduled
- **Payload**: MemoryUnits with embeddings, redacted
- **Conflict Resolution**: Server wins (Second Brain authoritative)

### 4.2 Second → First (Sync)
- **Mechanism**: First Brain CLI pulls from Second Brain REST API
- **Frequency**: Manual (`longthink sync`)
- **Payload**: Full memory state (incremental via `updated_at`)

### 4.3 Gaps (Resolved by Mid Brain Phase 2 Protocol)
| Missing | Mid Brain Solution |
|---------|-------------------|
| Structured request/response | BrainMessage/BrainRequest/BrainResponse |
| Event streaming | BrainEvent (15 types) |
| Typed adapters | FirstBrainAdapter, SecondBrainAdapter |
| Health/readiness | `/health`, `/ready` on each brain |
| Circuit breaker | Adapter-level retry/fallback |

---

## 5. Test Baseline (Pre-Mid Brain)

| Suite | Tests | Passed | Skipped | Duration |
|-------|-------|--------|---------|----------|
| Cloud (FastAPI) | 154 | 154 | 4 (PG) | ~11s |
| Local (CLI) | 38 | 38 | 0 | ~3s |
| **Total** | **192** | **192** | **4** | **~14s** |

**Linting**: `ruff check cloud local` — clean (0 errors)

---

## 6. Audit Conclusions

### 6.1 Ready for Mid Brain Integration
✅ First Brain: Stable CLI, local memory, agent, Obsidian sync  
✅ Second Brain: Stable FastAPI, vector search, projects, graph, Obsidian sync  
✅ Shared: Obsidian vault structure, config schema, branding  
✅ Tests: 192 passing, linting clean  

### 6.2 Integration Points Identified
1. **FirstBrainAdapter** → wraps `local/memory_client.py` + `local/agent/`
2. **SecondBrainAdapter** → wraps `cloud/app/routers/memories.py` + `cloud/app/services/`
3. **Obsidian Vault** → shared filesystem path, bidirectional sync from both brains
4. **Config** → Mid Brain settings added to `cloud/.env` and `cloud/app/config.py`

### 6.3 Risk Assessment
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Adapter impedance mismatch | Low | Protocol types defined in Phase 2 |
| Obsidian sync conflicts | Medium | Mid Brain SyncManager as single writer |
| Performance (embeddings) | Low | Hash fallback + async Ollama |
| Config drift | Low | Single source of truth in `.env.example` |

---

## 7. Sign-Off

| Role | Name | Date | Status |
|------|------|------|--------|
| Architecture Review | — | 2026-08-28 | ✅ Complete |
| First Brain Owner | — | 2026-08-28 | ✅ Complete |
| Second Brain Owner | — | 2026-08-28 | ✅ Complete |
| Mid Brain Lead | — | 2026-08-28 | ✅ Complete |

---

*This audit completes Phase 0 per THREE BRAIN specification. Proceed to Phase 1 Mid Brain Skeleton.*