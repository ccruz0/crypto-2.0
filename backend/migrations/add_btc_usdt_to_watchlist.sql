-- SQL script to add BTC_USDT to watchlist if it doesn't exist
-- This will restore it if it's deleted, or create it if it doesn't exist

-- First, check if it exists (deleted or not)
SELECT id, symbol, exchange, is_deleted 
FROM watchlist_items 
WHERE symbol = 'BTC_USDT' AND exchange = 'CRYPTO_COM';

-- If it exists but is deleted, restore it:
UPDATE watchlist_items 
SET is_deleted = false 
WHERE symbol = 'BTC_USDT' 
  AND exchange = 'CRYPTO_COM'
  AND is_deleted = true;

-- If it doesn't exist at all, insert it:
INSERT INTO watchlist_items (
    symbol, 
    exchange, 
    is_deleted, 
    alert_enabled, 
    trade_enabled, 
    sl_tp_mode,
    created_at
)
SELECT 
    'BTC_USDT',
    'CRYPTO_COM',
    false,
    false,
    false,
    'conservative',
    NOW()
WHERE NOT EXISTS (
    SELECT 1 
    FROM watchlist_items 
    WHERE symbol = 'BTC_USDT' 
      AND exchange = 'CRYPTO_COM'
);

-- Verify it exists and is active:
SELECT id, symbol, exchange, is_deleted, sl_tp_mode, trade_enabled, alert_enabled
FROM watchlist_items 
WHERE symbol = 'BTC_USDT' AND exchange = 'CRYPTO_COM';














