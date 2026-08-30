-- Persistent audit trail (spec sections 25/41). Never stores query text,
-- bodies or secrets - only operational metadata.

CREATE TABLE IF NOT EXISTS audit_events (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    kind TEXT NOT NULL,
    request_id TEXT,
    api_key_hint TEXT,
    method TEXT,
    path TEXT,
    status INT,
    duration_ms INT,
    result_count INT,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_events(ts DESC);
