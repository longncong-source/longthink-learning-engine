-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 09 migration (version 0006)
-- Agent execution records: standardized envelope, state machine
-- (ACCEPTED/RUNNING/COMPLETED/FAILED/CANCELLED), idempotency_key UNIQUE so a
-- consequential action is never executed twice for the same key.
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
CREATE TABLE IF NOT EXISTS agent_executions (
    id TEXT PRIMARY KEY,
    idempotency_key TEXT,
    actor_person_id TEXT REFERENCES persons(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL DEFAULT '',
    project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
    department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
    envelope TEXT NOT NULL DEFAULT '{}',
    permission_snapshot TEXT NOT NULL DEFAULT '{}',
    correlation_id TEXT NOT NULL DEFAULT '',
    backend_task_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACCEPTED',
    result TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exec_idem ON agent_executions(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_exec_actor ON agent_executions(actor_person_id);
CREATE INDEX IF NOT EXISTS idx_exec_status ON agent_executions(status);
