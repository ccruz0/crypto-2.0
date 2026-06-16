-- Phase 6A: Autonomous investigation scheduler tables

CREATE TABLE IF NOT EXISTS jarvis_investigation_schedules (
    id SERIAL PRIMARY KEY,
    schedule_id TEXT NOT NULL UNIQUE,
    template_id TEXT NOT NULL,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'api',
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jarvis_scheduled_investigation_tasks (
    id SERIAL PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE,
    schedule_id TEXT NOT NULL,
    template_id TEXT NOT NULL DEFAULT 'generic',
    objective TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    investigation_id TEXT,
    result_summary TEXT,
    error_message TEXT,
    scheduled_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jarvis_sched_inv_tasks_status
    ON jarvis_scheduled_investigation_tasks (status, scheduled_at);

CREATE INDEX IF NOT EXISTS idx_jarvis_sched_inv_tasks_schedule
    ON jarvis_scheduled_investigation_tasks (schedule_id, status);

CREATE TABLE IF NOT EXISTS jarvis_investigation_scheduler_leader (
    lock_key TEXT NOT NULL PRIMARY KEY,
    holder_id TEXT NOT NULL,
    acquired_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
