-- Jarvis Phase 4B: proposal linkage columns on jarvis_investigations
-- Boot-time migration: _ensure_jarvis_investigations_phase4b_columns() in database.py

ALTER TABLE jarvis_investigations ADD COLUMN IF NOT EXISTS proposal_task_id TEXT;
ALTER TABLE jarvis_investigations ADD COLUMN IF NOT EXISTS proposal_status TEXT;
