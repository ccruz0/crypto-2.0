# How to Add BTC_USDT to Watchlist

## Problem
BTC_USDT exists in `trading_config.json` but is not visible in the watchlist dashboard. This is because the watchlist is loaded from the database `watchlist_items` table, not just from the config file.

## Solutions

### Option 1: Use the Frontend UI (Recommended)
1. Go to the Watchlist tab in the dashboard
2. Click the **"+ Add Symbol"** button (top right)
3. Enter `BTC_USDT` in the input field
4. Click "Add"

This will:
- Add BTC_USDT to the `custom_top_coins` table
- Create a watchlist entry via `saveCoinSettings()`
- Make it visible in the watchlist immediately

### Option 2: Use the API Endpoint
If you have API access, you can call:

```bash
curl -X POST http://your-api-url/api/dashboard \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC_USDT",
    "exchange": "CRYPTO_COM",
    "alert_enabled": false,
    "trade_enabled": false,
    "sl_tp_mode": "conservative"
  }'
```

### Option 3: Run the Python Script (When Database is Accessible)
When you have database access (e.g., via Docker exec or SSH to server):

```bash
python3 backend/scripts/add_btc_usdt_to_watchlist.py
```

### Option 4: Run SQL Directly (When Database is Accessible)
Connect to your PostgreSQL database and run:

```sql
-- Check if it exists (including deleted entries)
SELECT id, symbol, exchange, is_deleted 
FROM watchlist_items 
WHERE symbol = 'BTC_USDT' AND exchange = 'CRYPTO_COM';

-- If it exists but is deleted, restore it:
UPDATE watchlist_items 
SET is_deleted = false 
WHERE symbol = 'BTC_USDT' 
  AND exchange = 'CRYPTO_COM'
  AND is_deleted = true;

-- If it doesn't exist, insert it:
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
```

The complete SQL script is available at: `backend/migrations/add_btc_usdt_to_watchlist.sql`

## Why BTC_USDT Wasn't Visible

The watchlist dashboard loads data from two sources:
1. **Trading Config** (`trading_config.json`) - Contains strategy presets (✅ BTC_USDT is here)
2. **Database** (`watchlist_items` table) - Contains actual watchlist entries (❌ BTC_USDT was missing here)

Both need to exist for a symbol to appear in the watchlist. The config file provides the strategy settings, but the database entry makes it visible in the UI.

## After Adding BTC_USDT

Once BTC_USDT is added to the watchlist:
- It will appear when you search for "btc" in the watchlist
- It will use the "swing" preset and "conservative" risk mode (as configured in `trading_config.json`)
- You can configure trade settings, alerts, and amounts in the UI














