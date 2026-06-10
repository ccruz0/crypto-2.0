-- Jarvis Control Center foundation: sessions, tasks, approvals, audit events.
-- Idempotent. Apply on PostgreSQL:
--   psql ... -f backend/migrations/add_jarvis_control_center_tables.sql
-- See docs/architecture/JARVIS_CONTROL_CENTER_IMPLEMENTATION_PLAN.md

CREATE TABLE IF NOT EXISTS jarvis_control_sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL,
    created_by VARCHAR(255) NOT NULL DEFAULT 'system',
    default_mode VARCHAR(32) NOT NULL DEFAULT 'advisor',
    environment VARCHAR(16) NOT NULL DEFAULT 'prod',
    domain VARCHAR(32) NOT NULL DEFAULT 'general',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    metadata_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_jarvis_control_sessions_session_id UNIQUE (session_id)
);

CREATE INDEX IF NOT EXISTS ix_jarvis_control_sessions_session_id ON jarvis_control_sessions (session_id);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_sessions_status ON jarvis_control_sessions (status);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_sessions_created_by_created_at
    ON jarvis_control_sessions (created_by, created_at DESC);

CREATE TABLE IF NOT EXISTS jarvis_control_tasks (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(128) NOT NULL,
    session_id VARCHAR(128) NOT NULL REFERENCES jarvis_control_sessions (session_id) ON DELETE CASCADE,
    mode VARCHAR(32) NOT NULL DEFAULT 'advisor',
    domain VARCHAR(32) NOT NULL DEFAULT 'general',
    prompt TEXT NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    risk_level VARCHAR(16) NOT NULL DEFAULT 'low',
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    plan_json TEXT,
    tool_results_json TEXT,
    final_answer TEXT,
    estimated_cost_usd NUMERIC,
    builder_artifact_json TEXT,
    governance_task_id VARCHAR(128),
    legacy_task_run_id VARCHAR(128),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_jarvis_control_tasks_task_id UNIQUE (task_id)
);

CREATE INDEX IF NOT EXISTS ix_jarvis_control_tasks_task_id ON jarvis_control_tasks (task_id);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_tasks_session_id ON jarvis_control_tasks (session_id);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_tasks_status_created_at ON jarvis_control_tasks (status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_tasks_mode_domain ON jarvis_control_tasks (mode, domain);

CREATE TABLE IF NOT EXISTS jarvis_control_approvals (
    id SERIAL PRIMARY KEY,
    approval_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128) NOT NULL REFERENCES jarvis_control_tasks (task_id) ON DELETE CASCADE,
    action_id VARCHAR(128),
    approval_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    execution_status VARCHAR(32) NOT NULL DEFAULT 'not_executed',
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    scope_summary VARCHAR(2000),
    digest VARCHAR(128),
    allowed_envs VARCHAR(64),
    requested_by VARCHAR(255) NOT NULL DEFAULT 'jarvis',
    approved_by VARCHAR(255),
    approved_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    governance_manifest_id VARCHAR(128),
    agent_approval_state_id INTEGER,
    telegram_message_id VARCHAR(64),
    execution_result_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_jarvis_control_approvals_approval_id UNIQUE (approval_id)
);

CREATE INDEX IF NOT EXISTS ix_jarvis_control_approvals_approval_id ON jarvis_control_approvals (approval_id);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_approvals_task_id ON jarvis_control_approvals (task_id);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_approvals_approval_status ON jarvis_control_approvals (approval_status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_approvals_digest ON jarvis_control_approvals (digest);

CREATE TABLE IF NOT EXISTS jarvis_control_audit_events (
    id SERIAL PRIMARY KEY,
    event_id VARCHAR(128) NOT NULL,
    task_id VARCHAR(128),
    session_id VARCHAR(128),
    approval_id VARCHAR(128),
    ts TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    type VARCHAR(64) NOT NULL,
    actor_type VARCHAR(32) NOT NULL DEFAULT 'system',
    actor_id VARCHAR(255),
    environment VARCHAR(16) NOT NULL DEFAULT 'prod',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_jarvis_control_audit_events_event_id UNIQUE (event_id)
);

CREATE INDEX IF NOT EXISTS ix_jarvis_control_audit_events_task_ts ON jarvis_control_audit_events (task_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_audit_events_session_ts ON jarvis_control_audit_events (session_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_jarvis_control_audit_events_type_ts ON jarvis_control_audit_events (type, ts DESC);
