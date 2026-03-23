-- Governance layer: tasks, append-only events, approval manifests.
-- Idempotent. Apply on PostgreSQL: psql ... -f backend/migrations/20260322_create_governance_tables.sql
-- See docs/governance/IMPLEMENTATION_NOTES.md

CREATE TABLE IF NOT EXISTS governance_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    source_type VARCHAR(64) NOT NULL DEFAULT 'manual',
    source_ref VARCHAR(512),
    status VARCHAR(32) NOT NULL DEFAULT 'requested',
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    current_manifest_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_governance_tasks_task_id UNIQUE (task_id)
);

CREATE INDEX IF NOT EXISTS ix_governance_tasks_task_id ON governance_tasks (task_id);
CREATE INDEX IF NOT EXISTS ix_governance_tasks_status ON governance_tasks (status);

CREATE TABLE IF NOT EXISTS governance_events (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    event_id VARCHAR(128) NOT NULL,
    ts TIMESTAMPTZ NOT NULL,
    type VARCHAR(32) NOT NULL,
    actor_type VARCHAR(32) NOT NULL,
    actor_id VARCHAR(255),
    environment VARCHAR(16) NOT NULL DEFAULT 'prod',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_governance_events_event_id UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS ix_governance_events_task_ts ON governance_events (task_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_governance_events_type ON governance_events (type);

CREATE TABLE IF NOT EXISTS governance_manifests (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    manifest_id VARCHAR(128) NOT NULL,
    digest VARCHAR(128) NOT NULL,
    commands_json TEXT NOT NULL,
    scope_summary VARCHAR(2000),
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    approval_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    approved_by VARCHAR(255),
    approved_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_governance_manifests_manifest_id UNIQUE (manifest_id)
);

CREATE INDEX IF NOT EXISTS ix_governance_manifests_task_id ON governance_manifests (task_id);
CREATE INDEX IF NOT EXISTS ix_governance_manifests_manifest_id ON governance_manifests (manifest_id);
CREATE INDEX IF NOT EXISTS ix_governance_manifests_approval ON governance_manifests (approval_status);

COMMENT ON TABLE governance_tasks IS 'Governed work units; lifecycle state; optional pointer to current manifest.';
COMMENT ON TABLE governance_events IS 'Append-only audit stream (plan, action, finding, decision, result, error).';
COMMENT ON TABLE governance_manifests IS 'PROD mutation intent; digest binds approval to exact commands.';
