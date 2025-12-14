-- Migration: Add missing columns to signal_throttle_states table
-- Created: 2025-12-14
-- Purpose: Add previous_price and force_next_signal columns that are defined in the model but missing in the database

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

-- Add force_next_signal column if it doesn't exist
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'signal_throttle_states' 
        AND column_name = 'force_next_signal'
    ) THEN
        ALTER TABLE signal_throttle_states 
        ADD COLUMN force_next_signal BOOLEAN DEFAULT FALSE NOT NULL;
        
        RAISE NOTICE 'Column force_next_signal added to signal_throttle_states';
    ELSE
        RAISE NOTICE 'Column force_next_signal already exists in signal_throttle_states';
    END IF;
END $$;

