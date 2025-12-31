# Throttle Reset Investigation Report

## Code Map

### 1. Throttle Storage
- **Location**: `backend/app/models/signal_throttle.py`
- **Table**: `signal_throttle_states`
- **Key Fields**:
  - `symbol` (String, indexed)
  - `strategy_key` (String, indexed) 
  - `side` (BUY/SELL/INDEX, indexed)
  - `last_price` (Float) - baseline price
  - `last_time` (DateTime) - last signal timestamp
  - `force_next_signal` (Boolean) - bypass throttle flag
  - `config_hash` (String) - hash of config fields
- **Unique Constraint**: `(symbol, strategy_key, side)`

### 2. Throttle Key Builder
- **Location**: `backend/app/services/signal_throttle.py`
- **Function**: `build_strategy_key(strategy_type, risk_approach)`
- **Normalization**: `_normalize_strategy_key()` converts to lowercase `"{strategy}:{risk}"`
- **Usage**: Used in both dashboard endpoints and signal_monitor

### 3. Dashboard Update Endpoints
- **Location**: `backend/app/api/routes_market.py`
- **Endpoints**:
  - `PUT /watchlist/{symbol}/alert` (line 1258) - Legacy master alert toggle
  - `PUT /watchlist/{symbol}/buy-alert` (line 1367) - Buy alert toggle
  - `PUT /watchlist/{symbol}/sell-alert` (line 1494) - Sell alert toggle
- **Throttle Reset Logic**:
  - Lines 1449-1470: Buy alert toggle calls `reset_throttle_state()` and `set_force_next_signal()`
  - Lines 1576-1597: Sell alert toggle calls `reset_throttle_state()` and `set_force_next_signal()`
  - Strategy resolution: Uses `resolve_strategy_profile()` to get strategy_key

- **Location**: `backend/app/api/routes_dashboard.py`
- **Endpoints**:
  - `PUT /dashboard/coins` (line ~2000) - Bulk coin config update
  - `PUT /dashboard/coin/{symbol}` (line ~1692) - Single coin config update
- **Throttle Reset Logic**:
  - Lines 2009-2117: Config change detection using `compute_config_hash()`
  - Calls `reset_throttle_state()` and `set_force_next_signal()` for both BUY and SELL
  - Lines 2180-2270: Strategy change detection and throttle reset

### 4. Scheduler/Worker Loop
- **Location**: `backend/app/services/signal_monitor.py`
- **Main Loop**: `monitor_signals()` (line 728) - called periodically
- **Evaluation**: `_check_signal_for_coin_sync()` (line 752)
- **Throttle Check**:
  - Lines 1167-1182: Fetches signal snapshots using `fetch_signal_states()`
  - Lines 1187-1231: Checks config_hash and resets throttle if changed
  - Lines 1257-1267: Calls `should_emit_signal()` for BUY signals
  - Lines 1411-1421: Calls `should_emit_signal()` for SELL signals

### 5. Throttle Decision Logic
- **Location**: `backend/app/services/signal_throttle.py`
- **Function**: `should_emit_signal()` (line 98)
- **Bypass Logic**:
  - Lines 121-143: Checks `force_next_signal` flag first - if True, bypasses all throttling
  - Clears `force_next_signal` after first use
- **Throttle Rules**:
  - Fixed 60-second time gate (line 155)
  - Configurable price change % threshold (from config)
  - Both gates must pass (AND logic)

### 6. Config Hash Computation
- **Location**: `backend/app/services/signal_throttle.py`
- **Function**: `compute_config_hash()` (line 57)
- **Fields Included** (CONFIG_HASH_FIELDS, line 13):
  - `alert_enabled`
  - `buy_alert_enabled`
  - `sell_alert_enabled`
  - `trade_enabled`
  - `strategy_id`
  - `strategy_name`
  - `min_price_change_pct`
  - `trade_amount_usd`

## Potential Root Causes

### A. Strategy Key Mismatch
**Issue**: Dashboard and scheduler might build strategy_key differently
- Dashboard: Uses `resolve_strategy_profile()` then `build_strategy_key()`
- Scheduler: Uses `resolve_strategy_profile()` then `build_strategy_key()`
- **Status**: Both use same functions, but need to verify normalization

### B. Config Hash Not Updated on Dashboard Change
**Issue**: Dashboard might reset throttle but not update config_hash
- Dashboard endpoints DO call `reset_throttle_state()` with `config_hash` parameter
- Signal monitor checks config_hash and resets if changed
- **Status**: Both sides handle config_hash, but timing might be an issue

### C. Stale Snapshot in Signal Monitor
**Issue**: Signal monitor might fetch snapshots before dashboard commits
- Signal monitor fetches snapshots at line 1171
- Dashboard commits at line 1310 (buy alert) or 1549 (sell alert)
- **Status**: Possible race condition if scheduler runs immediately after dashboard update

### D. Force Flag Not Set Correctly
**Issue**: `force_next_signal` might not be set or cleared too early
- Dashboard sets `force_next_signal=True` via `set_force_next_signal()`
- `should_emit_signal()` checks and clears it (lines 122-143)
- **Status**: Logic looks correct, but need to verify it's actually being set

### E. Symbol Normalization
**Issue**: Symbol format might differ (ETH_USDT vs ETH-USDT)
- Dashboard: Uses `symbol.upper()` 
- Scheduler: Uses `symbol` from watchlist_item (should be uppercase)
- **Status**: Both should normalize, but need verification

## Root Cause Analysis

### Issue Found
The dashboard alert toggle endpoints (`PUT /watchlist/{symbol}/buy-alert` and `PUT /watchlist/{symbol}/sell-alert`) were calling `reset_throttle_state()` but were **missing two critical parameters**:
1. `current_price` - Not passed, causing a full reset (last_price=None) instead of setting baseline to current price
2. `config_hash` - Not passed, preventing the signal_monitor's config_hash check from detecting the change

### Impact
- Throttle was being reset, but without `config_hash`, the signal_monitor's config_hash comparison wouldn't detect the change
- Without `current_price`, the baseline price wasn't set correctly
- However, `force_next_signal` was being set correctly, which should still bypass throttling

### Fix Applied
Updated `backend/app/api/routes_market.py`:
- Added `compute_config_hash` import
- Modified `update_buy_alert()` endpoint to:
  - Fetch current_price from watchlist item or market data
  - Compute config_hash from watchlist item fields
  - Pass both `current_price` and `config_hash` to `reset_throttle_state()`
- Modified `update_sell_alert()` endpoint with same changes

This ensures consistency with `routes_dashboard.py` which already had these parameters.

## Investigation Plan

1. ✅ Build code map (this document)
2. ✅ Add diagnostic mode with decision trace
3. ✅ Verify reset trigger is actually called
4. ✅ Check for key mismatches
5. ✅ Implement fix (added config_hash and current_price to routes_market.py)
6. ✅ Add diagnostic script

## Changes Made

### 1. Diagnostic Mode (`backend/app/services/signal_monitor.py`)
- Added `DIAG_SYMBOL` environment variable support
- Added decision trace logging function `_print_decision_trace()`
- Added reason code constants (SKIP_*, EXEC_*)
- Filtered monitor_signals() to only process DIAG_SYMBOL when set
- Decision trace prints:
  - symbol, strategy, side
  - current_price, reference_price, price_change%
  - alert_enabled, trade_enabled
  - throttle_key
  - last_sent timestamp, now, elapsed, cooldown threshold
  - final decision and reason_code

### 2. Fix Dashboard Endpoints (`backend/app/api/routes_market.py`)
- Added `compute_config_hash` import
- Updated `update_buy_alert()` to pass `current_price` and `config_hash` to `reset_throttle_state()`
- Updated `update_sell_alert()` to pass `current_price` and `config_hash` to `reset_throttle_state()`
- Both endpoints now fetch current_price from watchlist item or market data
- Both endpoints compute config_hash from watchlist item fields

### 3. Diagnostic Script (`backend/scripts/diag_throttle_reset.py`)
- Script to test throttle reset after dashboard changes
- Checks initial throttle state
- Simulates dashboard change
- Verifies throttle reset and force_next_signal flag
- Usage: `DIAG_SYMBOL=ETH_USDT python scripts/diag_throttle_reset.py`

## How to Reproduce

1. Set `DIAG_SYMBOL=ETH_USDT` environment variable
2. Run scheduler - will only evaluate ETH_USDT and print decision trace
3. Toggle alert ON in dashboard for ETH_USDT
4. Check logs for decision trace showing:
   - Before: `SKIP_COOLDOWN_ACTIVE` (if cooldown was active)
   - After: `EXEC_ALERT_SENT` (should bypass throttle)

## Throttle Channel Analysis

### Shared Throttle Bucket
**Finding**: Throttle is **SHARED** between alerts and orders. There is no separate channel field.

- `should_emit_signal()` is the single gate that controls both alerts and orders
- If `should_emit_signal()` returns True, both alerts can be sent AND orders can be placed
- Throttle key format: `{symbol}:{strategy_key}:{side}` (no channel suffix)
- Decision trace shows: `throttle_key_alert` and `throttle_key_trade` are the same (shared)

### Implications
- Toggling alert ON resets throttle for both alerts and orders (shared bucket)
- Toggling trade ON resets throttle for both alerts and orders (shared bucket)
- Strategy/params change resets throttle for both (shared bucket)
- This is the correct behavior - one signal evaluation controls both actions

## UI Endpoints Validated

### Endpoints Fixed
1. ✅ `PUT /watchlist/{symbol}/buy-alert` - Now passes `config_hash` and `current_price`
2. ✅ `PUT /watchlist/{symbol}/sell-alert` - Now passes `config_hash` and `current_price`
3. ✅ `PUT /watchlist/{symbol}/alert` (legacy) - Now passes `config_hash` and `current_price`
4. ✅ `PUT /dashboard/symbol/{symbol}` - Now resets throttle when alert/trade/config changes

### Endpoints Already Correct
- `PUT /dashboard/{item_id}` - Already had comprehensive throttle reset logic
- `PUT /dashboard/coins` (bulk) - Already had throttle reset logic

### Frontend API Calls
- `updateBuyAlert()` → `PUT /watchlist/{symbol}/buy-alert` ✅
- `updateSellAlert()` → `PUT /watchlist/{symbol}/sell-alert` ✅
- `updateWatchlistAlert()` → `PUT /watchlist/{symbol}/alert` ✅
- `updateWatchlistItem()` → `PUT /dashboard/symbol/{symbol}` ✅
- `saveCoinSettings()` → `updateWatchlistItem()` → `PUT /dashboard/symbol/{symbol}` ✅

## How to Verify in Production

### Local Testing
1. Set `DIAG_SYMBOL=ETH_USDT` environment variable
2. Run scheduler - will only evaluate ETH_USDT and print decision trace
3. Toggle alert ON in dashboard for ETH_USDT
4. Check logs for decision trace showing:
   - Before: `SKIP_COOLDOWN_ACTIVE` (if cooldown was active)
   - After: `EXEC_ALERT_SENT` (should bypass throttle)
5. Toggle trade ON in dashboard for ETH_USDT
6. Verify decision trace shows `EXEC_ORDER_PLACED` if signal exists

### Diagnostic Script
```bash
DIAG_SYMBOL=ETH_USDT python backend/scripts/diag_throttle_reset.py
```

This script:
- Checks initial throttle state
- Simulates buy alert toggle ON
- Verifies throttle reset and force_next_signal
- Simulates trade toggle ON
- Verifies throttle reset for both sides

### Production Logs (AWS)
1. Check logs for `[DECISION_TRACE]` entries when `DIAG_SYMBOL` is set
2. Verify that after dashboard toggle, `force_next_signal=True` in throttle state
3. Verify that next scheduler evaluation shows `EXEC_ALERT_SENT` instead of `SKIP_COOLDOWN_ACTIVE`
4. If signal is false, verify reason code is `SKIP_NO_SIGNAL` (not cooldown)

### Commands to Check Logs
```bash
# Check for decision traces
grep "DECISION_TRACE" /path/to/logs

# Check for throttle reset logs
grep "Reset throttle state" /path/to/logs

# Check for force_next_signal
grep "force_next_signal" /path/to/logs
```

## Key Files Changed

1. `backend/app/services/signal_monitor.py` - Added diagnostic mode, decision trace, and reason codes
2. `backend/app/api/routes_market.py` - Fixed throttle reset in buy/sell/legacy alert endpoints
3. `backend/app/api/routes_dashboard.py` - Added throttle reset to PUT /dashboard/symbol/{symbol}
4. `backend/scripts/diag_throttle_reset.py` - Enhanced diagnostic script with buy alert and trade toggle tests
5. `backend/tests/test_throttle_reset.py` - New unit tests for throttle reset functionality
6. `docs/reports/throttle-reset-investigation.md` - This report

## Test Coverage

### Unit Tests (`backend/tests/test_throttle_reset.py`)
- ✅ Config hash changes trigger throttle reset
- ✅ reset_throttle_state sets force_next_signal correctly
- ✅ Symbol normalization works correctly
- ✅ Strategy key normalization works correctly
- ✅ force_next_signal is cleared after first use
- ✅ Reset can target both BUY and SELL sides

### Integration Tests
- Diagnostic script tests end-to-end flow:
  - Buy alert toggle → throttle reset → force_next_signal set
  - Trade toggle → throttle reset → force_next_signal set for both sides

## Commit Plan

1. **diag: decision trace + DIAG_SYMBOL + enhanced diag script for trade toggle**
   - Add DIAG_SYMBOL env var support
   - Add decision trace logging with reason codes
   - Extend diagnostic script to test buy alert and trade toggles

2. **fix: ensure ALL UI update endpoints pass config_hash/current_price and reset correct throttle channels**
   - Fix `/watchlist/{symbol}/alert` (legacy)
   - Fix `/watchlist/{symbol}/buy-alert`
   - Fix `/watchlist/{symbol}/sell-alert`
   - Fix `/dashboard/symbol/{symbol}`

3. **test: add regression tests for throttle reset**
   - Unit tests for config_hash changes
   - Unit tests for force_next_signal
   - Unit tests for symbol/strategy normalization

