# Ghost Order Fix Summary

## Problem
The Trading Dashboard showed a BTC_USDT BUY LIMIT order as ACTIVE, but this order does NOT exist in Crypto.com Exchange (confirmed by Order History / Open Orders UI).

## Root Cause
**File**: `backend/app/api/routes_dashboard.py` (lines 641-758) and `backend/app/api/routes_orders.py` (lines 965-1071)

**Issue**: The backend was merging database orders (from `ExchangeOrder` table) with cached Crypto.com API orders. Database orders with status `ACTIVE`, `NEW`, or `PARTIALLY_FILLED` were being added to the open orders list even if they didn't exist in the Crypto.com API response. This created "ghost orders" - orders that were cancelled/executed on Crypto.com but still marked as active in the database.

**Why BTC was injected**: The BTC order was likely:
1. Created and stored in the database with status `ACTIVE`
2. Cancelled or executed on Crypto.com Exchange
3. Database status was not updated (or sync failed)
4. The dashboard merge logic added it back because it had status `ACTIVE` in the database

## Solution

### 1. Fixed `routes_dashboard.py` (`_compute_dashboard_state`)
- **Before**: Merged database orders with cached Crypto.com orders, including any database order with status ACTIVE/NEW/PARTIALLY_FILLED
- **After**: Only uses cached Crypto.com orders as source of truth. Database orders are checked for logging purposes only (to detect ghost orders), but are NOT merged into the response.

**Key changes**:
- Removed database order merging logic (lines 646-758)
- Added logging to detect ghost orders (orders in database but not in Crypto.com)
- Crypto.com cache is now the single source of truth

### 2. Fixed `routes_orders.py` (`/api/orders/open` endpoint)
- **Before**: Returned all database orders with status ACTIVE/NEW/PARTIALLY_FILLED, plus SQLite orders
- **After**: Only returns orders from Crypto.com API cache (source of truth)

**Key changes**:
- Endpoint now uses `get_open_orders_cache()` to get orders from Crypto.com
- Converts `UnifiedOpenOrder` objects to frontend format
- Checks database for ghost orders (logging only)
- Removed SQLite order merging

### 3. Added Guardrails
- **Logging**: Added comprehensive logging to detect ghost orders:
  - Logs Crypto.com API response (order IDs and symbols)
  - Logs database orders with open status
  - Logs warnings when ghost orders are detected
- **Invariant**: "If an order is shown as OPEN, it must come from Crypto.com API and have an order_id"

## Files Modified

1. `backend/app/api/routes_dashboard.py`
   - Removed database order merging (lines 646-758)
   - Added ghost order detection and logging
   - Crypto.com cache is now the only source

2. `backend/app/api/routes_orders.py`
   - Completely rewrote `/api/orders/open` endpoint
   - Now uses Crypto.com cache instead of database
   - Added ghost order detection logging

## Verification Steps

1. **Check logs** for ghost order warnings:
   ```
   [GHOST_ORDERS] Detected X ghost orders in database that don't exist in Crypto.com
   [GHOST_ORDER] Dropping ghost order: <order_id> (<symbol>) - status=<status> - NOT in Crypto.com API response
   ```

2. **Verify Crypto.com API response**:
   ```
   [OPEN_ORDERS] Crypto.com API returned X open orders. Order IDs: [...], Symbols: [...]
   ```

3. **Check dashboard**:
   - BTC ghost order should no longer appear
   - Real open orders (ALGO, DOT, etc.) should still appear correctly
   - Dashboard should match Crypto.com Open Orders exactly

4. **Test `/api/orders/open` endpoint**:
   - Should only return orders from Crypto.com API
   - Response should include `"source": "crypto_com_api"`

## Expected Behavior After Fix

- ✅ Only orders that exist in Crypto.com Exchange are shown
- ✅ Ghost orders (stale database entries) are detected and logged, but NOT displayed
- ✅ Dashboard matches Crypto.com Open Orders UI exactly
- ✅ Real open orders (ALGO, DOT, etc.) continue to work correctly

## Minimal Fix Compliance

- ✅ No trading logic changes
- ✅ No Telegram logic changes
- ✅ Only data pipeline fixes
- ✅ Guardrails added (logging + invariant)
- ✅ Every order shown must exist in Crypto.com API response




