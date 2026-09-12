-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 03 migration (version 0003)
-- Organizational versions: the structure is time-variable, never a single
-- fixed chart. Departments/positions/teams/assignments already carry
-- effective_from/effective_to + status; this table versions each published
-- chart (e.g. v2026.01) so history can be listed and compared.
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
CREATE TABLE IF NOT EXISTS org_versions (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    effective_from TEXT,
    effective_to TEXT,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
