# Strategy Consistency Hardening Summary

## Changes Made

### 1. Removed trading_config.json Writes

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Changed**: `handleStrategyChange()` function

**Removed**:
- `updateCoinConfig()` call that wrote to `trading_config.json`
- Comment about "backward compatibility" write

**Rationale**: 
- `trading_config.json` is a preset catalog only, NOT state
- WatchlistItem.sl_tp_mode is the single source of truth for strategy state
- Backend's `resolve_strategy_profile()` reads preset from trading_config.json (catalog) and risk from WatchlistItem.sl_tp_mode (state)

**Current Behavior**:
- Only updates `WatchlistItem.sl_tp_mode` via `saveCoinSettings()`
- Clears local state to force using API values
- Logs warning if API response strategy_key doesn't match requested strategy

### 2. Added Regression Guards

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Added Guards**:

1. **Tooltip Guard** (`buildStrategyTooltip`):
   - Warns if `coin.strategy_key` exists but doesn't match computed strategy
   - Warns if `coin.strategy_key` is null but UI shows a strategy (using fallback)

2. **Dropdown Guard** (in render):
   - Verifies dropdown and tooltip use same strategy (they both call `getCoinStrategy()`)
   - Logs error if mismatch detected (should never happen)

3. **Update Guard** (`handleStrategyChange`):
   - Verifies API response `strategy_key` matches requested strategy
   - Logs warning if backend resolved different strategy

### 3. Updated Strategy Resolution

**File**: `frontend/src/app/components/tabs/WatchlistTab.tsx`

**Current Priority** (in `getCoinStrategy()`):
1. **API `strategy_key`** (single source of truth from WatchlistItem)
2. **API `strategy_preset` + `strategy_risk`** (construct if `strategy_key` missing)
3. Legacy fallbacks (for backward compatibility during migration)

**Note**: Fallbacks are read-only - they don't persist state

### 4. State Management

**Removed**:
- Optimistic update of `localCoinPresets` in `handleStrategyChange`
- Now clears `localCoinPresets` entry to force using API values

**Rationale**:
- `localCoinPresets` is a legacy fallback only
- UI should always prefer API values from WatchlistItem
- Clearing forces re-reading from API on next render

## Verification Steps

### 1. Run Consistency Check

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/watchlist_consistency_check.py
```

**Expected**:
- Report includes "Strategy (DB)" and "Strategy (API)" columns
- Zero strategy mismatches
- All strategies match between DB and API

### 2. Run E2E Verification

```bash
cd /Users/carloscruz/automated-trading-platform/backend
python3 scripts/verify_watchlist_e2e.py
```

**Expected**:
- Strategy write-through test passes
- Strategy consistency verified for all symbols
- All fields match including `strategy_key`

### 3. Manual UI Test

1. Open Dashboard → Watchlist tab
2. Find a coin (e.g., ADA_USD)
3. Check dropdown value and tooltip (hover over symbol)
4. **Verify**: Dropdown and tooltip show the same strategy
5. Change strategy in dropdown (e.g., "Swing Conservadora" → "Intradia Agresiva")
6. Check browser console - should see:
   - `✅ Strategy updated for ADA_USD: intraday-aggressive (sl_tp_mode=aggressive). DB is source of truth.`
   - No warnings about trading_config.json
7. Refresh page
8. **Verify**: Dropdown and tooltip still match and show the new strategy

### 4. Console Warnings

**Expected** (dev/test):
- No `[STRATEGY_MISMATCH]` warnings in console
- If warnings appear, investigate:
  - Dropdown/tooltip mismatch → bug in `getCoinStrategy()` usage
  - API strategy_key null but UI shows strategy → API not returning strategy fields
  - Update mismatch → backend resolved different strategy than requested

## Architecture Summary

### Data Flow

**Read Path**:
1. Backend `/api/dashboard` returns WatchlistItem with `strategy_key`, `strategy_preset`, `strategy_risk`
2. Frontend `getCoinStrategy()` prioritizes API `strategy_key`
3. Dropdown and tooltip both use `getCoinStrategy()` → always consistent

**Write Path**:
1. User selects strategy in dropdown (e.g., "intraday-aggressive")
2. `handleStrategyChange()` parses strategy key → preset="intraday", risk="aggressive"
3. Updates `WatchlistItem.sl_tp_mode="aggressive"` via `saveCoinSettings()`
4. Backend resolves full strategy (preset from trading_config.json catalog + risk from WatchlistItem)
5. API response includes updated `strategy_key`
6. Frontend clears local state, re-reads from API on next render

### Single Source of Truth

- **WatchlistItem.sl_tp_mode** = risk mode state (conservative/aggressive)
- **trading_config.json coins.{symbol}.preset** = preset catalog (read-only)
- **Backend `resolve_strategy_profile()`** = combines catalog preset + DB risk
- **API `strategy_key`** = canonical identifier (preset-risk) from backend resolution
- **Frontend UI** = displays API `strategy_key` only

## Files Modified

1. **frontend/src/app/components/tabs/WatchlistTab.tsx**
   - Removed `updateCoinConfig()` call from `handleStrategyChange()`
   - Added regression guards in `buildStrategyTooltip()` and dropdown render
   - Updated state management to clear local state after update
   - Added warning logs for strategy mismatches

## Summary

✅ **Removed trading_config.json writes** (catalog only, not state)  
✅ **Added regression guards** (warnings for mismatches)  
✅ **Updated state management** (clears local state, uses API)  
✅ **Dropdown and tooltip share same source** (cannot disagree)  
✅ **WatchlistItem.sl_tp_mode is source of truth** (DB-only write-through)

The frontend now enforces DB-only strategy state with no UI-side persistence or trading_config.json writes.

