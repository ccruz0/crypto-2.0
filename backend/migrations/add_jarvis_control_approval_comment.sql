-- Jarvis Control Center: optional approval comment (Phase 2A Step 7).
-- Idempotent: safe to run multiple times.

ALTER TABLE jarvis_control_approvals
ADD COLUMN IF NOT EXISTS comment TEXT;
