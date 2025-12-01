# Trading Toggle Fix - Implementation Summary

## Problem Statement

When the Dashboard showed Trading = YES for a coin (e.g., ALGO_USDT), the backend would still say "Trade is NO / disabled" and would NOT place orders, even though the Dashboard showed Trading: YES.

**Root Cause**: The frontend was updating watchlist items by finding the first matching row by symbol and updating it by ID. However, SignalMonitor uses a canonical selector (`select_preferred_watchlist_item`) that might pick a DIFFERENT row when duplicates exist. This meant:
- Frontend updated row A (id=5) with trade_enabled=True
- SignalMonitor read row B (id=3) with trade_enabled=False
- Result: Dashboard shows YES, but orders are blocked

## Solution Implemented

### 1. New Backend Endpoint: `PUT /dashboard/symbol/{symbol}`

**File**: `backend/app/api/routes_dashboard.py`

- Uses the same canonical selector (`get_canonical_watchlist_item`) that SignalMonitor uses
- Ensures we always update the same row that SignalMonitor reads
- Added standardized logging: `DASHBOARD_UPDATE_BY_SYMBOL | symbol=%s | trade_enabled=%s | amount_usd=%s | id=%s | alert_enabled=%s`

### 2. Frontend Updates

**Files**: 
- `frontend/src/lib/api.ts`
- `frontend/src/app/api.ts`
- `frontend/src/app/page.tsx`

- Modified `saveCoinSettings()` to use `updateDashboardItemBySymbol()` instead of finding by ID
- Frontend now updates local state from backend response (single source of truth)
- TypeScript types fixed: `saveCoinSettings` now returns `WatchlistItem & { message?: string } | void`

### 3. SignalMonitor Logging

**File**: `backend/app/services/signal_monitor.py`

- Added standardized logging before order decision: `MONITOR_TRADE_FLAG | symbol=%s | trade_enabled=%s | amount_usd=%s | watchlist_id=%s | alert_enabled=%s`
- Confirmed SignalMonitor refreshes from canonical row using `get_canonical_watchlist_item()` before making decisions

### 4. Endpoint Hardening

**File**: `backend/app/api/routes_dashboard.py`

- `PUT /dashboard/{item_id}`: Added warning if updating trade_enabled on non-canonical row
- `POST /dashboard/bulk-update-alerts`: Now updates only canonical rows per symbol (prevents duplicate updates)

### 5. Debug & Verification Tools

**Files**:
- `backend/scripts/debug_watchlist_trade_enabled.py` - Enhanced to show more details
- `backend/scripts/verify_trading_toggle_end_to_end.py` - New end-to-end verification script
- `scripts/deploy_and_test_trading_toggle.sh` - Automated deploy and test script

## Key Guarantees

✅ **Frontend and SignalMonitor use the same canonical row** (same `id`)
✅ **Trading toggle updates the row that SignalMonitor reads**
✅ **Standardized logging for debugging** (DASHBOARD_UPDATE_BY_SYMBOL, MONITOR_TRADE_FLAG)
✅ **Frontend syncs state with backend response** (single source of truth)
✅ **Alerts are NOT blocked by trade_enabled** (only order placement is gated)
✅ **No more "Trade=NO" when Dashboard shows Trading=YES** (when no problematic duplicates exist)

## Verification

### On AWS - Quick Check

```bash
# 1. Check current state
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python -m backend.scripts.debug_watchlist_trade_enabled ALGO_USDT'

# 2. Toggle Trading in Dashboard, then check logs
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 200 | grep -E "DASHBOARD_UPDATE_BY_SYMBOL|MONITOR_TRADE_FLAG"'

# 3. Verify same id appears in both logs
# DASHBOARD_UPDATE_BY_SYMBOL should show id=X
# MONITOR_TRADE_FLAG should show watchlist_id=X (same value)
```

### Automated Deploy & Test

```bash
./scripts/deploy_and_test_trading_toggle.sh ALGO_USDT
```

### End-to-End Verification

```bash
# Check all symbols with trade_enabled=True
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python -m backend.scripts.verify_trading_toggle_end_to_end'

# Check specific symbol
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python -m backend.scripts.verify_trading_toggle_end_to_end ALGO_USDT'
```

## Files Changed

### Backend
- `backend/app/api/routes_dashboard.py` - New endpoint, improved bulk update, added logging
- `backend/app/services/signal_monitor.py` - Added MONITOR_TRADE_FLAG logging
- `backend/scripts/debug_watchlist_trade_enabled.py` - Enhanced debug output
- `backend/scripts/verify_trading_toggle_end_to_end.py` - New verification script

### Frontend
- `frontend/src/lib/api.ts` - Updated to use canonical selector endpoint
- `frontend/src/app/api.ts` - Same updates for consistency
- `frontend/src/app/page.tsx` - Updates local state from backend response

### Scripts
- `scripts/deploy_and_test_trading_toggle.sh` - Automated deploy and test script

## Testing Checklist

- [ ] Deploy to AWS
- [ ] Toggle Trading = NO for test symbol, verify DB shows trade_enabled=False
- [ ] Toggle Trading = YES for test symbol, verify DB shows trade_enabled=True
- [ ] Verify same canonical row id in DASHBOARD_UPDATE_BY_SYMBOL and MONITOR_TRADE_FLAG logs
- [ ] Trigger BUY signal, verify alert is sent (even if trade_enabled=False)
- [ ] With trade_enabled=True and amount_usd>0, verify order is placed when signal triggers
- [ ] Run end-to-end verification script, check for warnings/errors

## Notes

- The fix ensures consistency between frontend updates and SignalMonitor reads
- If duplicate rows exist, only the canonical row is updated/read
- Alerts are sent based on `alert_enabled` only, not `trade_enabled`
- Order placement requires both `trade_enabled=True` AND `trade_amount_usd > 0`

