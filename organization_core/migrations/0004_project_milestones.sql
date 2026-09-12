-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 06 migration (version 0004)
-- Project milestones: Project/Risk/Issue/Decision tables already exist
-- (Phase 01); only milestones were missing for the horizontal layer.
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_milestones (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code TEXT,
    title TEXT NOT NULL,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_milestones_project ON project_milestones(project_id);
