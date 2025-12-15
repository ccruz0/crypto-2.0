-- Migration: Add emit_reason column to signal_throttle_states table
-- Created: 2025-12-15
-- Purpose: Store reason why signal was emitted (e.g., price change %, strategy change, side change)
--
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_emit_reason_to_signal_throttle.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_emit_reason_to_signal_throttle.sql

-- Add emit_reason column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'signal_throttle_states' 
        AND column_name = 'emit_reason'
    ) THEN
        ALTER TABLE signal_throttle_states 
        ADD COLUMN emit_reason VARCHAR(500) NULL;
        
        RAISE NOTICE 'Column emit_reason added to signal_throttle_states';
    ELSE
        RAISE NOTICE 'Column emit_reason already exists in signal_throttle_states';
    END IF;
END $$;

