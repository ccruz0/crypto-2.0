-- Migration to set all watchlist items to Swing conservative strategy
-- This sets sl_tp_mode to 'conservative' for all non-deleted watchlist items

UPDATE watchlist_items 
SET sl_tp_mode = 'conservative' 
WHERE is_deleted = false 
  AND (sl_tp_mode IS NULL OR sl_tp_mode != 'conservative');

-- Verify the update
SELECT symbol, sl_tp_mode, COUNT(*) as count
FROM watchlist_items
WHERE is_deleted = false
GROUP BY symbol, sl_tp_mode
ORDER BY symbol;














