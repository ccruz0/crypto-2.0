-- Migration: Add decision tracing fields to telegram_messages table
-- Created: 2025-01-XX
-- 
-- This migration adds fields to track why buy orders were SKIPPED or FAILED:
--   - decision_type: "SKIPPED" or "FAILED" - whether the buy was skipped before attempt or failed during attempt
--   - reason_code: Canonical reason code (e.g., "TRADE_DISABLED", "EXCHANGE_REJECTED")
--   - reason_message: Human-readable reason message
--   - context_json: JSON object with contextual data (prices, balances, thresholds, etc.)
--   - exchange_error_snippet: Raw exchange error message for FAILED decisions
--   - correlation_id: Optional correlation ID for tracing across logs
-- 
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_decision_tracing_fields.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_decision_tracing_fields.sql

-- Add decision_type column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'decision_type'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN decision_type VARCHAR(20);
        
        RAISE NOTICE '✅ Added decision_type column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  decision_type column already exists in telegram_messages table';
    END IF;
END $$;

-- Add reason_code column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'reason_code'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN reason_code VARCHAR(100);
        
        RAISE NOTICE '✅ Added reason_code column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  reason_code column already exists in telegram_messages table';
    END IF;
END $$;

-- Add reason_message column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'reason_message'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN reason_message TEXT;
        
        RAISE NOTICE '✅ Added reason_message column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  reason_message column already exists in telegram_messages table';
    END IF;
END $$;

-- Add context_json column (JSONB for PostgreSQL)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'context_json'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN context_json JSONB;
        
        RAISE NOTICE '✅ Added context_json column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  context_json column already exists in telegram_messages table';
    END IF;
END $$;

-- Add exchange_error_snippet column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'exchange_error_snippet'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN exchange_error_snippet TEXT;
        
        RAISE NOTICE '✅ Added exchange_error_snippet column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  exchange_error_snippet column already exists in telegram_messages table';
    END IF;
END $$;

-- Add correlation_id column
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'telegram_messages' 
        AND column_name = 'correlation_id'
    ) THEN
        ALTER TABLE telegram_messages 
        ADD COLUMN correlation_id VARCHAR(100);
        
        RAISE NOTICE '✅ Added correlation_id column to telegram_messages table';
    ELSE
        RAISE NOTICE 'ℹ️  correlation_id column already exists in telegram_messages table';
    END IF;
END $$;

-- Create indexes for efficient queries
CREATE INDEX IF NOT EXISTS ix_telegram_messages_decision_type 
    ON telegram_messages(decision_type);

CREATE INDEX IF NOT EXISTS ix_telegram_messages_reason_code 
    ON telegram_messages(reason_code);

CREATE INDEX IF NOT EXISTS ix_telegram_messages_correlation_id 
    ON telegram_messages(correlation_id);

-- Verify the columns were added
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'telegram_messages' 
AND column_name IN ('decision_type', 'reason_code', 'reason_message', 'context_json', 'exchange_error_snippet', 'correlation_id')
ORDER BY column_name;

-- Show sample of existing rows (should all have NULL for new fields until they're populated)
SELECT 
    id, 
    symbol, 
    blocked, 
    order_skipped,
    decision_type,
    reason_code,
    LEFT(reason_message, 80) as reason_message_preview,
    timestamp
FROM telegram_messages 
ORDER BY timestamp DESC 
LIMIT 5;

