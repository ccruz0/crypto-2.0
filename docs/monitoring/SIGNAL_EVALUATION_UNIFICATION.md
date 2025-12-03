# Signal Evaluation Unification

## Overview

This document describes the unification of signal evaluation logic between the live `SignalMonitorService` and the debug script `debug_live_signals_all.py`. Both now use the same canonical evaluation helper to ensure **exact** consistency.

## Problem

Previously, the debug script and live monitor used slightly different logic for:
- Indicator fetching (priority order)
- Signal calculation parameters
- Throttle checks
- Flag evaluation

This caused discrepancies where:
- `debug_live_signals_all.py` reported `SELL_SIGNALS_NOW: ['AVAX_USDT', 'LTC_USDT', 'AAVE_USDT']` with `CAN_SELL=✓`
- `SignalMonitorService` logs showed `decision=WAIT` and `index=0` for the same symbols
- No alerts were emitted despite the debug script showing signals

## Solution

Created a single canonical evaluation helper: `backend/app/services/signal_evaluator.py`

### Key Components

1. **`evaluate_signal_for_symbol()`** - The canonical evaluation function that:
   - Fetches indicators using the exact same priority as the debug script
   - Calls `calculate_trading_signals()` with identical parameters
   - Applies throttle checks using `should_emit_signal()`
   - Evaluates alert flags (`alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`)
   - Returns a structured `SignalEvalResult` with all decision details

2. **Refactored `debug_live_signals_all.py`**:
   - Now calls `evaluate_signal_for_symbol()` for each symbol
   - Uses the result to build the output table
   - Summary uses `can_emit_buy_alert` and `can_emit_sell_alert` from the result

3. **Refactored `SignalMonitorService._check_signal_for_coin_sync()`**:
   - Replaced ~400 lines of custom evaluation logic with a call to `evaluate_signal_for_symbol()`
   - Uses `can_emit_buy_alert` and `can_emit_sell_alert` from the result to drive alert emission
   - Logs `[LIVE_ALERT_DECISION]` with all values from the canonical result

## Decision Logic

The canonical decision rule (used by both debug script and live monitor):

```python
if buy_signal:
    decision = "BUY"
elif sell_signal:
    decision = "SELL"
else:
    decision = "WAIT"
```

**Important**: The decision is based on `buy_signal` and `sell_signal` booleans from `calculate_trading_signals()`, NOT on `strategy_state.decision`.

## Alert Emission Logic

Alerts are emitted only when:

```python
can_emit_buy_alert = buy_allowed (throttle) AND buy_flag_allowed (flags)
can_emit_sell_alert = sell_allowed (throttle) AND sell_flag_allowed (flags)
```

This matches exactly what the debug script prints as `CAN_BUY` and `CAN_SELL`.

## Logging

### Debug Script Output
- Table shows: `DECISION`, `CAN_BUY`, `CAN_SELL`, `BUY_THR`, `SELL_THR`
- Summary shows: `BUY_SIGNALS_NOW` and `SELL_SIGNALS_NOW` based on `can_emit_*_alert`

### Live Monitor Logs
- `[LIVE_ALERT_DECISION]` - One line per symbol per cycle with:
  - `decision`, `buy_signal`, `sell_signal`
  - `can_emit_buy`, `can_emit_sell`
  - `buy_allowed`, `sell_allowed` (throttle results)
  - `buy_flag_allowed`, `sell_flag_allowed` (flag results)
  - `index` (strategy index from `calculate_trading_signals`)
  - `buy_thr`, `sell_thr` (throttle status: SENT/BLOCKED/N/A)

- `[LIVE_BUY_CALL]` / `[LIVE_SELL_CALL]` - When alerts are about to be sent
- `[LIVE_BUY_SKIPPED]` / `[LIVE_SELL_SKIPPED]` - When alerts are not sent (with reason)
- `[ALERT_EMIT_FINAL]` - After alert emission attempt

## Verification

To verify the unification is working:

1. **Run debug script on AWS**:
   ```bash
   docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py"
   ```

2. **Check live monitor logs**:
   ```bash
   docker compose logs -f backend-aws | grep 'LIVE_ALERT_DECISION'
   ```

3. **Compare results**:
   - Symbols in `SELL_SIGNALS_NOW` with `CAN_SELL=✓` should show:
     - `decision=SELL` in `[LIVE_ALERT_DECISION]`
     - `can_emit_sell=True`
     - `[LIVE_SELL_CALL]` log entry
     - `[ALERT_EMIT_FINAL] side=SELL sent=True`

## Files Modified

1. **`backend/app/services/signal_evaluator.py`** (NEW)
   - Canonical evaluation helper

2. **`backend/scripts/debug_live_signals_all.py`**
   - Refactored to use `evaluate_signal_for_symbol()`

3. **`backend/app/services/signal_monitor.py`**
   - Replaced custom evaluation logic with call to `evaluate_signal_for_symbol()`
   - Updated alert emission to use `can_emit_buy_alert` and `can_emit_sell_alert`

## Benefits

1. **Single Source of Truth**: Both paths use identical logic
2. **Easier Debugging**: When debug script shows a signal, live monitor will too
3. **Consistent Index**: Same indicator window/index calculation
4. **Maintainability**: Changes to evaluation logic only need to be made in one place

