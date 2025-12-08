-- Migration: Add order_skipped column to telegram_messages table
-- Created: 2025-01-XX
-- 
-- This column distinguishes between:
--   - blocked: Alert was blocked (technical/guardrail errors)
--   - order_skipped: Order was skipped due to position limits (alert was still sent)
-- 
-- IMPORTANT: Position limits block ORDERS, not ALERTS.
-- When order_skipped=true, blocked must be false (alert was sent).
-- 
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_order_skipped_column.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_order_skipped_column.sql

-- Check if column already exists before adding
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'order_skipped'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN order_skipped BOOLEAN NOT NULL DEFAULT FALSE;
        
        RAISE NOTICE '✅ Added order_skipped column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  order_skipped column already exists in telegram_messages table';
    END IF;
END $$;

-- Create index for efficient queries
CREATE INDEX IF NOT EXISTS ix_telegram_messages_order_skipped 
    ON telegram_messages(order_skipped);

-- Verify the column was added
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns 
WHERE table_name = 'telegram_messages' 
AND column_name = 'order_skipped';

-- Show sample of existing rows (should all have order_skipped = false)
SELECT 
    id, 
    symbol, 
    blocked, 
    order_skipped, 
    LEFT(message, 80) as message_preview,
    timestamp
FROM telegram_messages 
ORDER BY timestamp DESC 
LIMIT 5;
