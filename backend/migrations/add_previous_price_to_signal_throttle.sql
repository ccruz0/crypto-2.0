-- Migration: Add previous_price column to signal_throttle_states table
-- Created: 2025-12-14
-- Purpose: Store previous price to calculate price change percentage in monitoring dashboard
--
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_previous_price_to_signal_throttle.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_previous_price_to_signal_throttle.sql

-- Add previous_price column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'signal_throttle_states' 
        AND column_name = 'previous_price'
    ) THEN
        ALTER TABLE signal_throttle_states 
        ADD COLUMN previous_price DOUBLE PRECISION NULL;
        
        RAISE NOTICE 'Column previous_price added to signal_throttle_states';
    ELSE
        RAISE NOTICE 'Column previous_price already exists in signal_throttle_states';
    END IF;
END $$;

