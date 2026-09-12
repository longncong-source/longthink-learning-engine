-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 11 migration (version 0007)
-- Audit: explicit spec columns (resource, authz result, policy, request and
-- correlation ids, result) + hash-chain columns for tamper evidence.
-- Policy registry: version + scope on policies, append-only policy_versions.
-- governance_kv: chain head/checkpoint counters.
-- All additions are NULL-able / defaulted: existing writers keep working.
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
ALTER TABLE audit_events ADD COLUMN resource TEXT;
ALTER TABLE audit_events ADD COLUMN resource_id TEXT;
ALTER TABLE audit_events ADD COLUMN authz_result TEXT;
ALTER TABLE audit_events ADD COLUMN policy_ref TEXT;
ALTER TABLE audit_events ADD COLUMN request_id TEXT;
ALTER TABLE audit_events ADD COLUMN correlation_id TEXT;
ALTER TABLE audit_events ADD COLUMN result TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_events ADD COLUMN prev_hash TEXT;
ALTER TABLE audit_events ADD COLUMN entry_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_audit_correlation ON audit_events(correlation_id);
CREATE INDEX IF NOT EXISTS idx_audit_request ON audit_events(request_id);

ALTER TABLE policies ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
ALTER TABLE policies ADD COLUMN scope TEXT NOT NULL DEFAULT 'global';

CREATE TABLE IF NOT EXISTS policy_versions (
    id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    scope TEXT NOT NULL DEFAULT 'global',
    rules TEXT NOT NULL DEFAULT '{}',
    effect TEXT NOT NULL DEFAULT 'allow',
    effective_from TEXT,
    effective_to TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    UNIQUE (policy_id, version)
);

CREATE TABLE IF NOT EXISTS governance_kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);
