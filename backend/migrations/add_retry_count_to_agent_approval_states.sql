-- Add retry_count column to agent_approval_states for retry limiting.
-- Safe to run multiple times (IF NOT EXISTS / idempotent).
ALTER TABLE agent_approval_states
  ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;
