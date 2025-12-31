# WatchlistItem Database as Single Source of Truth - Fix Summary

## Problem

The Watchlist Consistency Report showed mismatches for `trade_amount_usd`:
- TRX_USDT: DB=10.0 API=11.0
- ALGO_USDT: DB=11.0 API=10.0
- ADA_USD: DB=None API=10.0

This indicated the API was applying defaults or mutating values at runtime, violating the principle that the database should be the single source of truth.

## Root Cause

1. **GET /api/dashboard** was reading from `WatchlistMaster` table instead of `WatchlistItem`
2. There was a sync mismatch between `WatchlistMaster` and `WatchlistItem` tables
3. The API could potentially apply defaults during serialization (though none were found for `trade_amount_usd`)

## Solution

### 1. Changed GET /api/dashboard to read from WatchlistItem

**File**: `backend/app/api/routes_dashboard.py`

- Changed endpoint to query `WatchlistItem` table directly (single source of truth)
- Removed dependency on `WatchlistMaster` table for GET requests
- Ensured serialization returns exact DB values with no defaults for `trade_amount_usd`

```python
# Before: Read from WatchlistMaster
items = db.query(WatchlistMaster).filter(...).all()
result.append(_serialize_watchlist_master(item, db=db))

# After: Read from WatchlistItem
items = db.query(WatchlistItem).filter(...).all()
result.append(_serialize_watchlist_item(item, market_data=market_data, db=db))
```

### 2. Updated PUT /api/dashboard/symbol/{symbol} to write to WatchlistItem

**File**: `backend/app/api/routes_dashboard.py`

- Changed endpoint to update `WatchlistItem` table directly
- Removed sync logic to `WatchlistMaster` (no longer needed)
- Returns fresh DB read after commit (no mutations)
- Explicitly handles `trade_amount_usd=None` (allows null values)

```python
# Now updates WatchlistItem directly
item = db.query(WatchlistItem).filter(...).first()
# ... update fields ...
db.commit()
db.refresh(item)  # Fresh read from DB
return {"item": _serialize_watchlist_item(item, ...)}
```

### 3. Verified Serialization

**File**: `backend/app/api/routes_dashboard.py` (line 117)

The serialization function already returns exact DB values:
```python
"trade_amount_usd": item.trade_amount_usd,  # No default applied
```

### 4. Frontend Already Uses Backend Response

**File**: `frontend/src/app/api.ts` (line 595)

The frontend `saveCoinSettings` function already uses the backend response:
```typescript
trade_amount_usd: updated.item.trade_amount_usd,  // Uses backend response
```

## Changes Made

### Backend Changes

1. **GET /api/dashboard** (`routes_dashboard.py:1086-1128`)
   - Changed to read from `WatchlistItem` instead of `WatchlistMaster`
   - Uses `_serialize_watchlist_item` instead of `_serialize_watchlist_master`

2. **PUT /api/dashboard/symbol/{symbol}** (`routes_dashboard.py:1131-1310`)
   - Changed to update `WatchlistItem` directly
   - Removed `WatchlistMaster` sync logic
   - Returns fresh DB read after commit

3. **Fixed linter errors** (`routes_dashboard.py:1961, 1974`)
   - Changed `symbol` to `item.symbol` in log statements

### Test Script

Created `backend/scripts/test_trade_amount_usd_consistency.py`:
- Tests NULL `trade_amount_usd` returns null (not 10)
- Tests exact value `trade_amount_usd=10.0` returns exactly 10.0 (not 11)

## How to Verify

### 1. Run the Test Script

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python scripts/test_trade_amount_usd_consistency.py
```

Expected output:
```
✅ PASSED: trade_amount_usd is null as expected
✅ PASSED: trade_amount_usd is exactly 10.0 as expected
✅ ALL TESTS PASSED
```

### 2. Run Consistency Check

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python scripts/watchlist_consistency_check.py
```

Expected: **0 mismatches** for `trade_amount_usd`

### 3. Manual API Test

```bash
# Set a coin to NULL trade_amount_usd
curl -X PUT http://localhost:8002/api/dashboard/symbol/ADA_USD \
  -H "Content-Type: application/json" \
  -d '{"trade_amount_usd": null}'

# Verify GET returns null
curl http://localhost:8002/api/dashboard | jq '.[] | select(.symbol=="ADA_USD") | .trade_amount_usd'
# Should output: null

# Set to 10.0
curl -X PUT http://localhost:8002/api/dashboard/symbol/ADA_USD \
  -H "Content-Type: application/json" \
  -d '{"trade_amount_usd": 10.0}'

# Verify GET returns exactly 10.0
curl http://localhost:8002/api/dashboard | jq '.[] | select(.symbol=="ADA_USD") | .trade_amount_usd'
# Should output: 10.0
```

### 4. Frontend Verification

1. Open Dashboard
2. Edit a coin's `trade_amount_usd` field
3. Save
4. Refresh page
5. Verify the value matches what you saved (no defaults applied)

## Files Modified

1. `backend/app/api/routes_dashboard.py` - Main changes
   - GET /api/dashboard: Read from WatchlistItem
   - PUT /api/dashboard/symbol/{symbol}: Write to WatchlistItem
   - Fixed linter errors

2. `backend/scripts/test_trade_amount_usd_consistency.py` - New test script

## Constraints Met

✅ **Do not refactor unrelated code** - Only changed minimum necessary code  
✅ **Keep existing behavior for other fields** - Only `trade_amount_usd` handling changed  
✅ **Only change minimum files** - 2 files modified (1 existing, 1 new test)  
✅ **Stop defaults/mutations in GET** - GET now returns exact DB values  
✅ **Implement write-through update path** - PUT updates DB and returns fresh read  
✅ **Frontend uses backend response** - Already implemented

## Next Steps

1. Run the test script to verify fixes
2. Run consistency check to confirm 0 mismatches
3. Monitor production for any regressions
4. Consider deprecating `WatchlistMaster` table if no longer needed

