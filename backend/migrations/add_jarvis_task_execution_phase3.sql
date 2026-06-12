-- Jarvis Phase 3 task execution framework (reference migration)
-- Applied automatically at boot via database.py ensure_* helpers.

ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS objective TEXT DEFAULT '';
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS priority TEXT DEFAULT 'normal';
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS artifacts_json JSONB;
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS approval_required BOOLEAN DEFAULT FALSE;
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS approval_status TEXT DEFAULT 'not_required';
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS actual_cost_usd NUMERIC DEFAULT 0;
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS current_step TEXT;
ALTER TABLE jarvis_task_runs ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS jarvis_execution_log (
    id SERIAL PRIMARY KEY,
    log_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    tool TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    duration_ms INTEGER DEFAULT 0,
    metadata_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_jarvis_execution_log_task_id ON jarvis_execution_log (task_id);

CREATE TABLE IF NOT EXISTS jarvis_task_approvals (
    id SERIAL PRIMARY KEY,
    approval_id TEXT NOT NULL UNIQUE,
    task_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_jarvis_task_approvals_task_id ON jarvis_task_approvals (task_id);
