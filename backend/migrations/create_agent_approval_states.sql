-- Agent approval state: persist Telegram approval requests and decisions.
-- Idempotent: safe to run multiple times (IF NOT EXISTS).
-- Run: PGPASSWORD=... psql -U trader -d atp -f backend/migrations/create_agent_approval_states.sql
-- Or apply via run_migration / create_all (model is registered in app.models).

CREATE TABLE IF NOT EXISTS agent_approval_states (
    id SERIAL PRIMARY KEY,
    task_id VARCHAR(255) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    approved_by VARCHAR(255),
    decision_at TIMESTAMPTZ,
    approval_summary TEXT,
    prepared_bundle_json TEXT,
    UNIQUE(task_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_approval_states_task_id ON agent_approval_states (task_id);
CREATE INDEX IF NOT EXISTS idx_agent_approval_states_status ON agent_approval_states (status);
CREATE INDEX IF NOT EXISTS idx_agent_approval_states_requested_at ON agent_approval_states (requested_at DESC);

COMMENT ON TABLE agent_approval_states IS 'Agent task approval requests and decisions; source of truth for Telegram approve/deny.';
