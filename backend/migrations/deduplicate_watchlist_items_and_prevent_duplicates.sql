-- Migration: Deduplicate watchlist_items and prevent future duplicates
-- Purpose:
-- - If accidental duplicate rows exist for the same (symbol, exchange), keep one canonical active row
--   and mark the others as deleted (is_deleted = true).
-- - Add a UNIQUE partial index to prevent multiple ACTIVE rows per (symbol, exchange).
--
-- Notes:
-- - Uses a partial unique index (WHERE is_deleted = false) to support soft-delete history.
-- - Designed for PostgreSQL (uses DO $$ and window functions).
--
-- 1) Ensure is_deleted exists (legacy safety)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'watchlist_items'
          AND column_name = 'is_deleted'
    ) THEN
        ALTER TABLE watchlist_items
        ADD COLUMN is_deleted BOOLEAN NOT NULL DEFAULT FALSE;

        RAISE NOTICE '✅ Added is_deleted column to watchlist_items table';
    END IF;
END $$;

-- 2) Mark duplicate ACTIVE rows as deleted, keeping one preferred row per (symbol, exchange)
-- Preference order (best first):
-- - is_deleted = false
-- - alert_enabled = true
-- - created_at newest
-- - id highest
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY symbol, exchange
            ORDER BY
                CASE WHEN is_deleted THEN 1 ELSE 0 END ASC,
                CASE WHEN alert_enabled THEN 0 ELSE 1 END ASC,
                created_at DESC NULLS LAST,
                id DESC
        ) AS rn
    FROM watchlist_items
)
UPDATE watchlist_items w
SET is_deleted = TRUE
FROM ranked r
WHERE w.id = r.id
  AND r.rn > 1
  AND w.is_deleted = FALSE;

-- 3) Prevent future duplicates among ACTIVE rows
DO $$
BEGIN
    -- Only attempt if exchange column exists (should exist in modern schema)
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'watchlist_items'
          AND column_name = 'exchange'
    ) THEN
        EXECUTE 'CREATE UNIQUE INDEX IF NOT EXISTS uq_watchlist_symbol_exchange_active
                 ON watchlist_items (symbol, exchange)
                 WHERE is_deleted = false';

        RAISE NOTICE '✅ Ensured unique active index uq_watchlist_symbol_exchange_active on (symbol, exchange) WHERE is_deleted=false';
    ELSE
        RAISE NOTICE '⚠️ exchange column missing on watchlist_items; skipping unique index creation';
    END IF;
END $$;

-- 4) Verification: show any remaining active duplicates (should return 0 rows)
SELECT
    symbol,
    exchange,
    COUNT(*) AS active_rows
FROM watchlist_items
WHERE is_deleted = false
GROUP BY symbol, exchange
HAVING COUNT(*) > 1
ORDER BY active_rows DESC, symbol ASC;












