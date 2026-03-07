-- Add durable execution state to agent_approval_states to prevent duplicate execution.
-- Idempotent: safe to run multiple times (ADD COLUMN IF NOT EXISTS).
-- Run: psql ... -f backend/migrations/add_agent_approval_execution_state.sql

ALTER TABLE agent_approval_states ADD COLUMN IF NOT EXISTS execution_status VARCHAR(20) DEFAULT 'not_started';
ALTER TABLE agent_approval_states ADD COLUMN IF NOT EXISTS execution_started_at TIMESTAMPTZ;
ALTER TABLE agent_approval_states ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ;
ALTER TABLE agent_approval_states ADD COLUMN IF NOT EXISTS execution_summary TEXT;

CREATE INDEX IF NOT EXISTS idx_agent_approval_states_execution_status ON agent_approval_states (execution_status);

COMMENT ON COLUMN agent_approval_states.execution_status IS 'not_started | running | completed | failed';
