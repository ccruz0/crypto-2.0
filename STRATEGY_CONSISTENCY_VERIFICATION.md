# Strategy Consistency Verification

## Overview

This document describes the strategy consistency verification system that ensures the Dashboard UI displays the correct strategy for each coin, matching what's stored in the database.

## Problem Statement

Previously, there was a mismatch where:
- Dashboard dropdown showed "Swing Conservadora" 
- Backend tooltip said "Estrategia: No strategy"

This indicated the frontend was using `trading_config.json` while the backend wasn't resolving the strategy correctly.

## Solution

### 1. Strategy Fields in Database

**WatchlistItem Model** (`backend/app/models/watchlist.py`):
- `sl_tp_mode`: String field storing risk mode ("conservative" or "aggressive")
- This is the only strategy field stored directly in WatchlistItem

**Full Strategy Resolution**:
- Strategy is resolved from `trading_config.json` using `resolve_strategy_profile()`
- Format: `preset-risk` (e.g., "swing-conservative", "intraday-aggressive")
- Preset comes from `trading_config.json` → `coins.{symbol}.preset`
- Risk comes from WatchlistItem → `sl_tp_mode`

### 2. API Response Enhancement

**GET /api/dashboard** (`backend/app/api/routes_dashboard.py`):
- Now includes resolved strategy fields:
  - `strategy_preset`: "swing", "intraday", or "scalp"
  - `strategy_risk`: "conservative" or "aggressive"
  - `strategy_key`: "swing-conservative" (canonical identifier)

**Implementation**:
```python
# In _serialize_watchlist_item()
from app.services.strategy_profiles import resolve_strategy_profile
strategy_type, risk_approach = resolve_strategy_profile(
    symbol=item.symbol,
    db=db,
    watchlist_item=item
)
serialized["strategy_preset"] = strategy_type.value if strategy_type else None
serialized["strategy_risk"] = risk_approach.value if risk_approach else None
serialized["strategy_key"] = f"{strategy_type.value}-{risk_approach.value}" if both else None
```

### 3. Consistency Check Enhancement

**Updated Script** (`backend/scripts/watchlist_consistency_check.py`):
- Added `get_resolved_strategy_key()` function to resolve strategy from DB
- Compares resolved strategy between DB and API
- Normalizes "no strategy" representations (None, "None", "No strategy")
- Reports mismatches clearly: `strategy: DB=swing-conservative, API=None`

**Report Table**:
- Added "Strategy (DB)" and "Strategy (API)" columns
- Highlights mismatches with ⚠️

### 4. Frontend Type Updates

**Updated Types** (`frontend/src/lib/api.ts`):
- Added `strategy_preset`, `strategy_risk`, `strategy_key` to `WatchlistItem` interface
- Frontend can now use API values instead of `trading_config.json`

**Note**: Frontend still uses `coinPresets` from `trading_config.json` for the dropdown. This should be updated to use `strategy_preset` and `strategy_risk` from the API response for consistency.

### 5. Verification Scripts

**Updated** (`backend/scripts/verify_watchlist_e2e.py`):
- Added `verify_strategy_write_through()` function
- Verifies that updating `sl_tp_mode` reflects in `strategy_key`
- Tests strategy consistency in read verification

## How to Verify

### 1. Run Consistency Check

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/watchlist_consistency_check.py
```

**Expected Output**:
- Report includes "Strategy (DB)" and "Strategy (API)" columns
- Zero mismatches for strategy
- Example: `ADA_USD: strategy: DB=swing-conservative, API=swing-conservative ✓`

### 2. Run End-to-End Verification

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/verify_watchlist_e2e.py
```

**Expected Output**:
- Strategy consistency verified for all symbols
- Strategy write-through test passes
- All fields match including `strategy_key`

### 3. Manual API Test

```bash
# Check API returns strategy fields
curl -s http://localhost:8002/api/dashboard | jq '.[] | select(.symbol=="ADA_USD") | {symbol, strategy_preset, strategy_risk, strategy_key}'

# Expected output:
# {
#   "symbol": "ADA_USD",
#   "strategy_preset": "swing",
#   "strategy_risk": "conservative",
#   "strategy_key": "swing-conservative"
# }
```

### 4. Verify Frontend Uses API Values

**Current State**: Frontend uses `coinPresets` from `trading_config.json`

**Recommended**: Update frontend to use `strategy_preset` and `strategy_risk` from API response:
- Dropdown should use `item.strategy_preset` and `item.strategy_risk` from `/api/dashboard`
- Tooltip should use the same values
- This ensures dropdown and tooltip always match

## Files Modified

1. **backend/app/api/routes_dashboard.py**
   - Added strategy resolution to `_serialize_watchlist_item()`
   - Returns `strategy_preset`, `strategy_risk`, `strategy_key`

2. **backend/scripts/watchlist_consistency_check.py**
   - Added `get_resolved_strategy_key()` function
   - Added strategy comparison in `check_consistency()`
   - Updated report table to include strategy columns

3. **backend/scripts/verify_watchlist_e2e.py**
   - Added `verify_strategy_write_through()` function
   - Added strategy to fields checked in `verify_read_consistency()`

4. **frontend/src/lib/api.ts**
   - Added strategy fields to `WatchlistItem` interface

## Next Steps (Frontend)

To complete the fix, update the frontend to use API strategy values:

1. **Update dropdown selection**:
   - Use `item.strategy_preset` and `item.strategy_risk` from API
   - Fallback to `coinPresets` only if API values are missing

2. **Update tooltip**:
   - Use same `strategy_preset` and `strategy_risk` from API
   - Ensure tooltip matches dropdown

3. **Update save action**:
   - When strategy changes, update `sl_tp_mode` in WatchlistItem
   - Backend will resolve full strategy and return it in response

## Summary

✅ **API returns resolved strategy** (`strategy_preset`, `strategy_risk`, `strategy_key`)  
✅ **Consistency check compares strategy** between DB and API  
✅ **Verification scripts test strategy** write-through and consistency  
✅ **Frontend types updated** to include strategy fields  
⚠️ **Frontend still uses trading_config.json** - should be updated to use API values

The backend now provides the resolved strategy in the API response, ensuring the frontend can display the correct strategy that matches the database.

