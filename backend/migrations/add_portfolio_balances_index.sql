-- Migration: Add composite index for portfolio_balances table
-- Purpose: Optimize portfolio summary queries that get latest balance per currency
-- Date: 2025-12-22

-- This index optimizes the window function query:
-- SELECT currency, balance, usd_value
-- FROM (
--     SELECT currency, balance, usd_value,
--            ROW_NUMBER() OVER (PARTITION BY currency ORDER BY id DESC) as rn
--     FROM portfolio_balances
-- ) ranked
-- WHERE rn = 1

CREATE INDEX IF NOT EXISTS idx_portfolio_balances_currency_id 
ON portfolio_balances(currency, id DESC);

-- Verify index was created
SELECT 
    indexname, 
    indexdef 
FROM pg_indexes 
WHERE tablename = 'portfolio_balances' 
AND indexname = 'idx_portfolio_balances_currency_id';

