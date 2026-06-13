-- Jarvis Phase 4A: production diagnostic investigation memory
-- Boot-time creation: ensure_jarvis_investigations_table() in database.py

CREATE TABLE IF NOT EXISTS jarvis_investigations (
    id SERIAL PRIMARY KEY,
    investigation_id TEXT NOT NULL UNIQUE,
    objective TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'api',
    template_id TEXT NOT NULL DEFAULT 'generic',
    status TEXT NOT NULL DEFAULT 'running',
    summary TEXT,
    root_cause TEXT,
    confidence NUMERIC DEFAULT 0,
    evidence_json JSONB,
    recommended_fix TEXT,
    impact TEXT,
    ranked_causes_json JSONB,
    verification_steps_json JSONB,
    next_action TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jarvis_investigations_created_at
    ON jarvis_investigations (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_jarvis_investigations_status
    ON jarvis_investigations (status);
