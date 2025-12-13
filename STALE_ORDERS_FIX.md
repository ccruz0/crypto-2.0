# Stale Orders Fix

## Problem
The dashboard was showing BTC open orders that don't actually exist on the Crypto.com exchange. This happens when:
1. Orders are cancelled on the exchange but the database still shows them as ACTIVE
2. The sync process fails or doesn't run frequently enough
3. Trigger orders (STOP_LIMIT, TAKE_PROFIT_LIMIT) weren't being checked during sync

## Root Cause
The `sync_open_orders` method in `exchange_sync.py` had two issues:
1. It only checked regular orders against the exchange, not trigger orders
2. It only marked orders as CANCELLED if there were orders in the response, missing edge cases

## Fixes Applied

### 1. Improved Sync Logic (`backend/app/services/exchange_sync.py`)
- **Fixed**: Now includes both regular orders AND trigger orders when checking for stale orders
- **Fixed**: Checks for stale orders even when exchange returns empty list
- **Result**: All order types (LIMIT, STOP_LIMIT, TAKE_PROFIT_LIMIT, etc.) are now properly validated

### 2. New API Endpoint (`backend/app/api/routes_orders.py`)
- **Added**: `POST /api/orders/verify-stale` endpoint
- **Purpose**: Manually verify orders against exchange and mark stale ones as CANCELLED
- **Usage**: Can be called with optional `symbol` parameter to check specific symbol

### 3. Verification Script (`backend/scripts/verify_and_cleanup_stale_orders.py`)
- **Added**: Standalone script to verify and cleanup stale orders
- **Usage**: Can be run from command line with `--symbol` and `--dry-run` options

## How to Use

### Option 1: Use the API Endpoint (Recommended)
```bash
# Verify all orders
curl -X POST "http://your-server:8002/api/orders/verify-stale" \
  -H "X-API-Key: your-api-key"

# Verify specific symbol (e.g., BTC_USDT)
curl -X POST "http://your-server:8002/api/orders/verify-stale?symbol=BTC_USDT" \
  -H "X-API-Key: your-api-key"
```

### Option 2: Run the Script (On Server)
```bash
# Verify all orders
cd /path/to/automated-trading-platform
python3 backend/scripts/verify_and_cleanup_stale_orders.py

# Verify specific symbol
python3 backend/scripts/verify_and_cleanup_stale_orders.py --symbol BTC_USDT

# Dry run (see what would be changed without making changes)
python3 backend/scripts/verify_and_cleanup_stale_orders.py --symbol BTC_USDT --dry-run
```

## What Happens
1. Script/endpoint fetches all active orders from database (NEW, ACTIVE, PARTIALLY_FILLED)
2. Fetches actual open orders from Crypto.com exchange (including trigger orders)
3. Compares database orders with exchange orders
4. Marks orders that don't exist on exchange as CANCELLED
5. Returns report of valid vs stale orders

## Prevention
The improved sync logic will now:
- Check both regular and trigger orders every sync cycle (every 5 seconds)
- Properly mark stale orders as CANCELLED automatically
- Prevent future accumulation of stale orders

## Testing
After applying the fix:
1. The sync process should automatically clean up stale orders
2. You can manually trigger cleanup using the API endpoint
3. The dashboard should only show orders that actually exist on the exchange

## Notes
- The sync runs every 5 seconds automatically
- Manual cleanup can be triggered anytime via the API
- Stale orders are marked as CANCELLED (not deleted) to preserve history

