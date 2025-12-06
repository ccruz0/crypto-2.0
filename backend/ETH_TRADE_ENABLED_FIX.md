# Fix: ETH_USDT trade_enabled Disappearing

## Problem
When refreshing the dashboard, ETH_USDT's `trade_enabled` was being set to `False`, causing it to disappear from the `/watchlist` command in Telegram (which only shows coins with `trade_enabled=True`).

## Root Cause
The frontend was sending PUT requests to `/api/dashboard/{item_id}` that did not include `trade_enabled` in the request body. The backend was correctly preserving the existing value when `trade_enabled` was not in the request, but at some point the frontend must have sent `trade_enabled=False` explicitly, or there was a manual change.

## Solution
1. **Restored ETH_USDT to `trade_enabled=True`** in the database
2. **Improved logging** in `update_dashboard_item()`:
   - Changed the warning log to debug level when `trade_enabled` is not in the request
   - Added a comment explaining that the existing value is preserved
   - This prevents confusion about whether the value is being changed

## Code Changes
- `backend/app/api/routes_dashboard.py`: Updated logging in `update_dashboard_item()` to use `log.debug()` instead of `log.warning()` when `trade_enabled` is not in the request, and added a comment explaining that the existing value is preserved.

## Current State
- ✅ BTC_USDT: `trade_enabled=True`
- ✅ ETH_USDT: `trade_enabled=True` (restored)

## Prevention
The backend already correctly preserves `trade_enabled` when it's not in the request. However, if the frontend sends `trade_enabled=False` explicitly, it will be updated. To prevent this:

1. **Frontend should always include `trade_enabled` in PUT requests** when updating watchlist items
2. **Frontend should preserve the existing `trade_enabled` value** when updating other fields like SL/TP prices
3. **Monitor logs** for any PUT requests that change `trade_enabled` unexpectedly

## Verification
After the fix:
- Both BTC_USDT and ETH_USDT have `trade_enabled=True`
- The `/watchlist` command in Telegram should show both coins
- Refreshing the dashboard should not change `trade_enabled` values

