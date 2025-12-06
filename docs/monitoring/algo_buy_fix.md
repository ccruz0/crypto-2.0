# ALGO_USDT BUY Alert Fix - Root Cause and Solution

## Problem
ALGO_USDT was not sending BUY alerts even when all BUY criteria were green in the tooltip.

## Root Cause

The backend's `calculate_trading_signals` function was using a different logic path to set `buy_signal` than the frontend uses to display the tooltip. Specifically:

1. **Frontend tooltip** checks `buy_*` reasons in `strategy_state.reasons` (e.g., `buy_rsi_ok`, `buy_volume_ok`, `buy_ma_ok`, `buy_target_ok`)
2. **Backend logic** was checking `decision.should_buy && buy_target_allows && volume_ok` which could fail even when all `buy_*` reasons were True

This mismatch caused situations where:
- Frontend tooltip showed all BUY criteria green (all `buy_*` reasons = True)
- Backend returned `buy_signal=False` and `decision=WAIT`
- No BUY alert was sent

## Solution

Added a **canonical rule** in `calculate_trading_signals` that aligns the BUY decision directly with the `buy_*` reasons used by the frontend:

```python
# CANONICAL RULE: Align BUY decision with buy_* reasons (same as frontend tooltip)
buy_flags = {
    k: v for k, v in strategy_state["reasons"].items() 
    if k.startswith("buy_") and isinstance(v, bool)
}

# If all buy_* flags are True, override to BUY (unless there's an active SELL signal)
all_buy_reasons_true = bool(buy_flags) and all(buy_flags.values())

if all_buy_reasons_true and not result["sell_signal"]:
    result["buy_signal"] = True
    strategy_state["decision"] = "BUY"
```

This ensures that when all BUY criteria are green in the tooltip (all `buy_*` reasons = True), the backend will:
- Set `strategy["decision"] = "BUY"`
- Set `signals["buy_signal"] = True`
- Allow BUY alerts to be sent (subject to throttle/risk checks)

## Files Changed

### backend/app/services/trading_signals.py
**Location**: `calculate_trading_signals()` function, before the final decision logic (around line 598)

**Change**: Added canonical rule that checks all `buy_*` reasons and overrides to BUY if all are True:

```python
# CANONICAL RULE: Align BUY decision with buy_* reasons (same as frontend tooltip)
buy_flags = {
    k: v for k, v in strategy_state["reasons"].items() 
    if k.startswith("buy_") and isinstance(v, bool)
}

all_buy_reasons_true = bool(buy_flags) and all(buy_flags.values())

if all_buy_reasons_true and not result["sell_signal"]:
    result["buy_signal"] = True
    strategy_state["decision"] = "BUY"
```

This ensures the backend decision matches what the frontend tooltip displays.

### backend/app/services/signal_monitor.py
- Added `[DEBUG_MONITOR_SYMBOLS]` logging to show all symbols being monitored
- Added `[DEBUG_ALGO_MARKET_DATA]` logging for market data availability
- Added `[DEBUG_ALGO_STRATEGY]` logging after `calculate_trading_signals` call
- Added `[DEBUG_ALGO_ALERT_GATE]` logging for throttle and risk checks
- Added `[DEBUG_ALGO_ALERT_SENT]` logging when alert is sent

## Expected Behavior After Fix
When all BUY criteria are satisfied (all `buy_*` reasons = True):
- Backend `decision=BUY` and `buy_signal=True` (canonical rule ensures this)
- Watchlist shows BUY (green chip)
- Telegram alert is sent (subject to throttle/risk checks) OR INFO diagnostic explains why it was blocked

## How to Debug Similar Issues

1. Check if the symbol is in the monitor: Look for `[MONITOR_CANONICAL]` logs
2. Check market data: Look for `[DEBUG_ALGO_MARKET_DATA]` logs
3. Check strategy decision: Look for `[STRATEGY_DECISION]` logs with `decision=BUY/WAIT/SELL`
4. Check buy_* reasons: The canonical rule will log `buy_flags` when all are True
5. Check alert gating: Look for `[DEBUG_ALGO_ALERT_GATE]` logs for throttle/risk blocks
