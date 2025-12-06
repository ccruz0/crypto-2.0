-- Migration: Add min_price_change_pct column to watchlist_items table
-- Created: 2025-01-XX
-- 
-- This column stores the minimum price change percentage required for order creation/alerts
-- Default value: 3.0 (if not set, backend will use 3.0% as default)
-- 
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_min_price_change_pct_column.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_min_price_change_pct_column.sql

-- Check if column already exists before adding
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'watchlist_items' 
        AND column_name = 'min_price_change_pct'
    ) THEN
        ALTER TABLE watchlist_items 
        ADD COLUMN min_price_change_pct FLOAT;
        
        RAISE NOTICE '✅ Added min_price_change_pct column to watchlist_items table';
    ELSE
        RAISE NOTICE 'ℹ️  min_price_change_pct column already exists in watchlist_items table';
    END IF;
END $$;

-- Verify the column was added
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'watchlist_items' 
AND column_name = 'min_price_change_pct';

