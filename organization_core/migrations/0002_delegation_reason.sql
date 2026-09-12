-- ============================================================================
-- LONGTHINK ORGANIZATION CORE — Phase 02 migration (version 0002)
-- Adds Delegation.reason (Phase 02 spec: delegated_by/to, scope,
-- start_at/end_at mapped to effective_from/to, reason, status).
-- Applied once via schema_migrations version tracking in store.init_schema.
-- ============================================================================
ALTER TABLE delegations ADD COLUMN reason TEXT;
