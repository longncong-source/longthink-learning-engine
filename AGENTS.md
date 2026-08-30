# AGENTS.md — LongThink Learning Engine

> **Source of truth is executable config.** If docs conflict with `pyproject.toml` / `pytest.ini` / `*.env.example` / `scripts/*.ps1`, trust the executable.

## Project Identity
- **Name** `longthink-learning-engine` `1.0.0` (`pyproject.toml` `requires-python >=3.13`, actual venv `3.12.10`)
- **Architecture** `First Brain` (local, **LONG-TERM** durable `local_data/long_term.sqlite3`) ↔ `Mid Brain` (intelligence `mid_brain/`) ↔ `Second Brain` (online **SHORT-TERM** cache `cloud/` via OpenClaw/ChatGPT/Gemini, `SHORT_TERM_TTL_DAYS=7`); **UI = Human Knowledge Interface ↔ Mid Brain** (`cloud/app/ui/` mounted on Second Brain but logically Human→Mid)
- **Ports** API `:8100` → `8000` in container, DB `:5433` → `:5432` (`docker-compose.brain.yml` `fsb-api`/`fsb-db`)
- **Repo roots** Code lives at `C:\Users\admin\OneDrive\Desktop\FirstSecondBrain` — this `Default Project` workspace is a mirror. Run all commands from `FirstSecondBrain` root.

## Setup & Run
```powershell
.\INSTALL.bat                          # one-click: setup.ps1 → venv + deps + .env + API :8100 + demo --yes
.\scripts\setup.ps1                    # manual: venv + requirements + copy .env.example → .env (skips if exists)
.\scripts\start_all.ps1                # auto-detect Ollama → sets EMBEDDING_PROVIDER/LLM_PROVIDER (hash/none offline, ollama online) + starts API if down
.\scripts\serve.ps1                    # start API hidden if not already on :8100; polls /health 2min
.\.venv\Scripts\python.exe -m uvicorn cloud.app.main:app --port 8100   # foreground, no auto-detect

# Brain CLI (all go through scripts/brain.ps1 wrapper → .venv python -m local.brain_cli)
.\scripts\brain.ps1 doctor --quick     # diagnostics (avoid `doctor` without --quick in CI)
.\scripts\brain.ps1 demo --yes         # 10-step MVP loop, human-in-loop auto-approved
.\scripts\brain.ps1 status; .\scripts\brain.ps1 sync   # pending-write SQLite outbox
.\scripts\brain.ps1 memory search "query"; .\scripts\brain.ps1 memory add --title t --content c --type decision
.\scripts\brain.ps1 project create "Name"; .\scripts\brain.ps1 doc upload file.pdf
.\scripts\brain.ps1 obsidian scan; .\scripts\brain.ps1 obsidian sync <file>; .\scripts\brain.ps1 obsidian export <mem_id>

# Direct API (Obsidian)
# POST /v1/obsidian/sync      {file, content, project_id?, default_type?, source?}
# POST /v1/obsidian/vault-sync {vault_path, project_id?, default_type?, source?}
```

## Test / Lint (exact order, exact paths)
```powershell
.\.venv\Scripts\python.exe -m pytest -q                 # testpaths=cloud/tests local/tests (pytest.ini): 192 passed, 4 skipped (PG integration auto-skips without Docker)
.\.venv\Scripts\python.exe -m pytest mid_brain/tests/ -q # 47 passed (23 core + 24 master loop) — NOT included in default testpaths
.\.venv\Scripts\python.exe -m ruff check cloud local scripts mid_brain  # line-length 100, py310, excludes .venv/app/data/documents/ollama (tool.ruff.exclude)
```
No `requirements-dev.txt` — dev deps are `pyproject.toml [project.optional-dependencies]` + `cloud/requirements.txt` + `local/requirements.txt`. Do not invent it. `docker-compose.yml` + `app/` is legacy RAG (Qdrant) — untouched.

## Env Files (gitignored, never commit)
| File | Key vars |
|------|----------|
| `cloud/.env` | **SHORT-TERM** online: `SHORT_TERM_TTL_DAYS=7`, `ONLINE_LLM_PROVIDER=openclaw|openai|gemini`, `ONLINE_LLM_MODEL=gpt-4o`, `OPENCLAW/OPENAI/GEMINI_API_KEY`, plus `MEMORY_API_KEYS=dev-local-key`, `MEMORY_DB_BACKEND=sqlite|postgres` (cache), `EMBEDDING_PROVIDER=hash|ollama|openai_compatible`, `EMBEDDING_DIMENSION=384`, `WEIGHT_*` (0.60/0.20/0.10/0.10), `DEDUPE_THRESHOLD=0.92`, `MID_BRAIN_*` (12 flags) |
| `local/.env` | **LONG-TERM** local: `LOCAL_LONG_TERM_DB=local_data/long_term.sqlite3`, `LOCAL_DATA_DIR=local_data`, `LLM_PROVIDER=ollama|none`, plus **Second SHORT-TERM online**: `SECOND_BRAIN_URL=http://127.0.0.1:8100`, `SECOND_BRAIN_PROVIDER=openclaw|chatgpt|gemini`, `SECOND_BRAIN_MODEL=gpt-4o`, `OPENCLAW/OPENAI/GEMINI_API_KEY`, `DATA_POLICY=local_only|selective|cloud_allowed`, `OBSIDIAN_VAULT_PATH`, `CACHE_TTL_SECONDS=600` |
| `start_all.ps1` | **Mutates** both `.env` on every run based on Ollama probe — reversible but surprises git diff. |

## Monorepo Boundaries & Entrypoints
- `cloud/` — Second Brain (SHORT-TERM online cache, internet, OpenClaw/ChatGPT/Gemini, `SHORT_TERM_TTL_DAYS=7`) FastAPI: `app/main.py` (create_app, lifespan init_schema, ObservabilityMiddleware + CORSMiddleware), `routers/` health/memories/projects/documents/admin/graph/obsidian/mid_brain, `repositories/` SqliteRepository/PostgresRepository (cache, TTL), `services/` memory_service (validate→redact→verify project→embed→dedupe→store), `ui/` Human Knowledge Interface (`cloud/app/ui/` StaticFiles at `/ui/`, Human ↔ Mid Brain)
- `local/` — First Brain (LONG-TERM durable, duy nhất có trạng thái dài hạn `local_data/long_term.sqlite3`): `brain_cli.py` entry (`python -m local.brain_cli`), `agent.py` 8-phase OBSERVE→RETRIEVE→THINK→PLAN→EXECUTE→VERIFY→REFLECT→STORE, `memory_client.py` SecondBrainClient (short-term online cache via `SECOND_BRAIN_PROVIDER=openclaw|chatgpt|gemini`, cache 600s, SQLite outbox, DATA_POLICY gate), `obsidian_service.py` scan/sync
- `mid_brain/` — Intelligence: `core/mid_brain.py` MidBrainConfig (13 fields) + `cognitive_orchestrator.py` 14-step loop, `api/brain_protocol.py` 15 message types, plus `confidence/planning/agent/network/feedback/obsidian` (vault_manager/note_generator/sync_manager/frontmatter), `tests/` not auto-collected
- `docker-compose.brain.yml` is the MVP stack; `docker-compose.yml` is legacy — do not mix.

## Hard-Earned Conventions
- **Auth** `X-API-Key: <key>` or `Authorization: Bearer <key>` (csv `MEMORY_API_KEYS`); `GET /health` no auth → `{"status":"ok"}`, `GET /health/details` needs auth.
- **Hybrid search** `final = w_sem*semantic + w_kw*keyword + w_imp*importance + w_rec*recency`, `recency = 0.5^(age_days/RECENCY_HALF_LIFE_DAYS)`, weights normalized to 1.0.
- **Dedupe** cosine ≥ `DEDUPE_THRESHOLD` → merge/update, not insert.
- **Redaction** deterministic regex `cloud/app/redaction.py` + `local/redaction.py` (sk-proj-*, ghp_*, AKIA*, Bearer *, password=*); audit never logs query/bodies.
- **Audit** `kind=http|memory_write`, `/ui/*` and `/health` skipped; CORS `*` but auth still enforced.
- **Obsidian** only `sync_to_brain: true` frontmatter syncs; `03_Resources→semantic, 01_Projects→project, 04_Lessons→lesson, 05_Decisions→decision`; AI→Human draft→approve, Human→Obsidian→Mid via `sync_from_obsidian()` → FeedbackEvent → LearningEngine.
- **Mid Brain API** all `/v1/mid-brain/*` require key: `GET health/status`, `POST process {question,project_id,context}`, `POST knowledge`, `GET memory/stats knowledge/stats learning/stats`.
- **Embeddings** hash dim 384 offline fallback if Ollama unreachable; `EMBEDDING_DIMENSION` mismatch breaks search.

## Gotchas
1. Docker optional — SQLite fallback is intended (default `MEMORY_DB_BACKEND=sqlite`). PG tests auto-skip.
2. Run from `FirstSecondBrain` root — scripts use `Split-Path -Parent $PSScriptRoot` to find `.venv`.
3. `start_all.ps1` overwrites `LLM_PROVIDER`/`EMBEDDING_PROVIDER` in `.env` — commit will show diff after first run; restore from `.env.example` if needed.
4. `local/.env` `LLM_MODEL=gemma4:12b` vs example `llama3.2` — not breaking, but Ollama needs `ollama pull llm_model`.
5. Legacy `app/` / `docker-compose.yml` (Qdrant/Open WebUI :8000/:6333/:3000) untouched — MVP uses `:8100/:5433`.

## Verify After Change
```powershell
.\.venv\Scripts\python.exe -m pytest -q; .\.venv\Scripts\python.exe -m pytest mid_brain/tests/ -q
.\.venv\Scripts\python.exe -m ruff check cloud local scripts mid_brain
.\scripts\brain.ps1 doctor --quick; .\scripts\brain.ps1 demo --yes
# then: curl http://127.0.0.1:8100/health  # expect {"status":"ok"}
```

## Reference Docs (not exhaustive)
`docs/architecture.md` · `docs/api.md` · `docs/memory-model.md` · `docs/security.md` · `docs/deployment.md` · `docs/PHASE_0_SYSTEM_AUDIT.md` · `docs/PHASE_1_MID_BRAIN_SKELETON.md` · `docs/PHASE_2_BRAIN_PROTOCOL.md` · `docs/PHASE_3_12_ADVANCED_COMPONENTS.md` · `FIRST_SECOND_BRAIN.md` · `THREE BRAIN — MID BRAIN MASTER ARCHITECTURE` spec
