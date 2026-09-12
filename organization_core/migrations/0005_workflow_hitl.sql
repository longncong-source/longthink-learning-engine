-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 07 migration (version 0005)
-- Task: owner / department / dependencies / source (HITL execution context).
-- Approval: resource / reason / decision / policy_snapshot / idempotency_key
-- (unique) / expires_at (HITL audit trail + idempotent execution).
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
ALTER TABLE tasks ADD COLUMN owner_person_id TEXT REFERENCES persons(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN department_id TEXT REFERENCES departments(id) ON DELETE SET NULL;
ALTER TABLE tasks ADD COLUMN dependencies TEXT NOT NULL DEFAULT '[]';
ALTER TABLE tasks ADD COLUMN source TEXT;
CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner_person_id);

ALTER TABLE approvals ADD COLUMN resource TEXT;
ALTER TABLE approvals ADD COLUMN reason TEXT;
ALTER TABLE approvals ADD COLUMN decision TEXT;
ALTER TABLE approvals ADD COLUMN policy_snapshot TEXT NOT NULL DEFAULT '{}';
ALTER TABLE approvals ADD COLUMN idempotency_key TEXT;
ALTER TABLE approvals ADD COLUMN expires_at TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_approvals_idem ON approvals(idempotency_key);
