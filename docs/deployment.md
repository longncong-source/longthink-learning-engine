# LongThink Learning Engine — Deployment & operations

## A. Laptop / development (no Docker required)

```powershell
.\scripts\setup.ps1                       # venv + deps + env files
.\.venv\Scripts\python.exe -m uvicorn cloud.app.main:app --port 8100   # terminal 1
.\.venv\Scripts\python.exe -m local.brain_cli demo --yes               # terminal 2
```
Backend: `MEMORY_DB_BACKEND=sqlite`, data at `data/second_brain.sqlite3`.

## B. Docker Compose (PostgreSQL + pgvector) — MVP target

```powershell
docker compose -f docker-compose.brain.yml up -d --build
# api  -> http://127.0.0.1:8100   (container 8000)
# db   -> localhost:5433          (container 5432)
```

- Image `pgvector/pgvector:pg16`; migrations in `cloud/migrations/*.sql` are
  applied automatically on container start (`cloud/container_init.py` waits for
  the DB, applies idempotent SQL, then execs uvicorn).
- Point the local brain at it: `SECOND_BRAIN_URL=http://127.0.0.1:8100`.
- Switch API to Postgres: compose sets `MEMORY_DB_BACKEND=postgres`.
- Using Ollama embeddings from inside Docker: keep
  `EMBEDDING_BASE_URL=http://host.docker.internal:11434` and set
  `EMBEDDING_PROVIDER=ollama` (plus matching `EMBEDDING_DIMENSION`,
  e.g. 768 for nomic-embed-text).

## Migrations

```bash
psql "postgresql://second_brain:second_brain@localhost:5433/second_brain" \
     -f cloud/migrations/0001_init.sql
```
All migrations are idempotent (`IF NOT EXISTS`) — safe to re-run.

## Backup & restore (§45)

```bash
# backup
docker exec fsb-db pg_dump -U second_brain -d second_brain -F c -f /tmp/sb.dump
docker cp fsb-db:/tmp/sb.dump ./backups/sb-$(date +%F).dump

# restore
docker cp ./backups/sb-2026-08-25.dump fsb-db:/tmp/sb.dump
docker exec fsb-db pg_restore -U second_brain -d second_brain --clean --if-exists /tmp/sb.dump

# sqlite fallback
Copy-Item data\second_brain.sqlite3 backups\
```
Never rely on managed-provider backups alone; schedule your own dumps.

## Cloud targets (provider-neutral, §3)

| Target | Notes |
|---|---|
| Supabase | Postgres+pgvector managed; set `DATABASE_URL` to its pooler URL |
| Railway / Render | deploy `cloud/Dockerfile`; attach managed Postgres with pgvector |
| Fly.io | `fly launch --dockerfile cloud/Dockerfile`; volume for PG or Neon |
| VPS | compose file as-is behind nginx/caddy TLS |

Only requirements: PostgreSQL ≥15 with `vector` extension, reachable URL.
The repository interface (`cloud/app/db.py`) keeps other backends possible.

## Environment separation (§44)

| File | Purpose |
|---|---|
| `.env` (root) | legacy RAG stack only - untouched |
| `cloud/.env` | Memory API config for local runs |
| `local/.env` | First Brain config (§22 names) |
| CI/tests | env injected by pytest fixtures; no real secrets |

Production checklist: rotate `MEMORY_API_KEYS`, set `ENVIRONMENT=production`,
restrict CORS if exposed beyond localhost, enable TLS at proxy, schedule backups.

## Backups (§45)

```powershell
.\scripts\backup.ps1                    # -> backups\second_brain-<stamp>.dump|.sqlite3
.\scripts\backup.sh [outdir] [keepdays]
```

- PostgreSQL: `pg_dump -F c` inside container `fsb-db`, copied out via `docker cp`.
- SQLite: uses the `sqlite3` online-backup API — required because WAL mode means
  a raw copy of `*.sqlite3` alone loses recent writes still sitting in `-wal`.
- Retention: files older than `-KeepDays 30` are pruned automatically.
  Schedule daily (Task Scheduler / cron) for production deployments.

## Upgrading dimensions later
`memories.embedding` is an untyped `vector` column so you can change embedding
models without migration. Once a dimension is final, add:
```sql
ALTER TABLE memories ALTER COLUMN embedding TYPE vector(768);
CREATE INDEX ON memories USING hnsw (embedding vector_cosine_ops);
```
