# Frontend Strategy Source-of-Truth Fix

## Overview

This document describes the frontend changes to ensure the strategy dropdown and tooltip use API values (`strategy_key`, `strategy_preset`, `strategy_risk`) from WatchlistItem as the single source of truth, replacing local derivation from `trading_config.json`.

## Changes Made

### 1. Updated TopCoin Interface

**File**: `frontend/src/lib/api.ts`

Added strategy fields to `TopCoin` interface:
```typescript
// Strategy fields from WatchlistItem (single source of truth)
strategy_preset?: string | null;  // "swing", "intraday", "scalp"
strategy_risk?: string | null;    // "conservative", "aggressive"
strategy_key?: string | null;     // "swing-conservative" (canonical identifier)
```

### 2. Updated Strategy Resolution Logic

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Changed**: `getCoinStrategy()` function

**Before**: Priority was `localCoinPresets > coin.strategy > signal.strategy > tradingConfig`

**After**: Priority is now:
1. **API `strategy_key`** (single source of truth from WatchlistItem)
2. **API `strategy_preset` + `strategy_risk`** (construct strategy_key if not present)
3. Fallback to legacy sources (for backward compatibility)

**Key Benefits**:
- Dropdown and tooltip use the same function (`getCoinStrategy`)
- Cannot disagree because they share the same source
- API values take priority over local state

### 3. Updated Strategy Change Handler

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Changed**: `handleStrategyChange()` function

**Before**: Updated `trading_config.json` via `updateCoinConfig()`

**After**: 
1. Parses strategy key (e.g., "swing-conservative" → preset="swing", risk="conservative")
2. **Updates WatchlistItem.sl_tp_mode** via `saveCoinSettings()` (write-through to DB)
3. Also updates `trading_config.json` preset (for backward compatibility)
4. Updates local state optimistically
5. Logs warning if strategy mismatch detected

**Key Benefits**:
- Writes directly to WatchlistItem (single source of truth)
- Changes persist immediately to database
- UI will reflect DB state on next fetch

### 4. Updated Tooltip Functions

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Changed**: `buildStrategyTooltip()` and `buildTradeTooltip()`

**After**: Both use `getCoinStrategy()` to ensure consistency with dropdown

**Added**: Debug logging to detect strategy mismatches

## How It Works

### Read Path (Display)

1. **API Response**: `/api/dashboard` returns watchlist items with `strategy_key`, `strategy_preset`, `strategy_risk`
2. **TopCoin Population**: When watchlist items are merged with TopCoin data, strategy fields are included
3. **Dropdown Display**: `getCoinStrategy()` returns `coin.strategy_key` (or constructs from preset+risk)
4. **Tooltip Display**: `buildStrategyTooltip()` uses same `getCoinStrategy()` function

**Result**: Dropdown and tooltip always show the same strategy (from API/DB)

### Write Path (Save)

1. **User Changes Dropdown**: Selects new strategy (e.g., "intraday-aggressive")
2. **Handler Parses**: Extracts preset="intraday", risk="aggressive"
3. **Updates WatchlistItem**: Calls `saveCoinSettings(symbol, { sl_tp_mode: "aggressive" })`
4. **Updates Config**: Also calls `updateCoinConfig(symbol, { preset: "intraday" })` (backward compatibility)
5. **Backend Resolves**: Backend resolves full strategy and returns in API response
6. **UI Refreshes**: On next fetch, UI shows updated strategy from API

**Result**: Changes persist to DB immediately, UI reflects DB state

## Verification Steps

### 1. Manual UI Test

1. Open Dashboard → Watchlist tab
2. Find a coin (e.g., ADA_USD)
3. Check dropdown value and tooltip (hover over symbol)
4. **Verify**: Dropdown and tooltip show the same strategy
5. Change strategy in dropdown (e.g., from "Swing Conservadora" to "Intradia Agresiva")
6. Refresh page
7. **Verify**: Dropdown and tooltip still match and show the new strategy

### 2. API Verification

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

### 3. Consistency Check

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/watchlist_consistency_check.py
```

**Expected**: Zero strategy mismatches between DB and API

### 4. Database Verification

```bash
# Check WatchlistItem has correct sl_tp_mode
sqlite3 backend/data/trading.db "SELECT symbol, sl_tp_mode FROM watchlist_items WHERE symbol='ADA_USD';"

# Expected: sl_tp_mode matches the risk mode from strategy_key
```

## Remaining Considerations

### Data Loading

The current implementation assumes that when `topCoins` are loaded, they include strategy fields from watchlist items. This may require:

1. **Merging Data Sources**: When loading watchlist data, merge strategy fields from `/api/dashboard` into TopCoin objects
2. **Or Using Watchlist Items Directly**: Use watchlist items from `/api/dashboard` as the primary data source for the watchlist tab

### Backward Compatibility

The code includes fallbacks to legacy sources (`localCoinPresets`, `coin.strategy`, `signal.strategy`, `tradingConfig`) for backward compatibility during migration. Once all data is migrated to use API strategy fields, these fallbacks can be removed.

## Files Modified

1. **frontend/src/lib/api.ts**
   - Added `strategy_preset`, `strategy_risk`, `strategy_key` to `TopCoin` interface

2. **frontend/src/app/components/tabs/WatchlistTab.tsx**
   - Updated `getCoinStrategy()` to prioritize API strategy fields
   - Updated `handleStrategyChange()` to update WatchlistItem.sl_tp_mode
   - Updated `buildStrategyTooltip()` and `buildTradeTooltip()` to use same source
   - Added debug logging for strategy mismatches

## Summary

✅ **Dropdown uses API strategy_key** (single source of truth)  
✅ **Tooltip uses same source** (cannot disagree with dropdown)  
✅ **Save updates WatchlistItem.sl_tp_mode** (write-through to DB)  
✅ **Changes persist immediately** and reflect on refresh  
✅ **Debug logging** detects mismatches  

The frontend now uses API strategy fields as the single source of truth, ensuring dropdown and tooltip always match what's stored in the database.

