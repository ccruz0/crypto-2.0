# BUY Decision Alignment - Frontend & Backend

## Problem Statement

Previously, there was a misalignment between the frontend tooltip (showing all BUY criteria green) and the backend decision (still showing WAIT). This caused:
- Frontend tooltip showing all BUY conditions satisfied
- Backend decision still showing WAIT
- BUY index < 100%
- BUY button not green
- No BUY alerts being sent

## Root Cause

1. **Frontend Override**: The frontend was overriding the backend decision using `hasBlockingStrategyReason()`, which checked if any `buy_*` reason was False and forced the decision to WAIT, even when the backend canonical rule had already set decision=BUY.

2. **Backend Canonical Rule**: The backend has a canonical rule that ensures if all `buy_*` boolean flags are True, then `decision=BUY` and `buy_signal=True`. However, the frontend was second-guessing this decision.

## Solution

### Backend Changes

**File**: `backend/app/services/trading_signals.py`

1. **Canonical BUY Rule** (lines 583-603):
   - Collects all `buy_*` flags that are explicitly boolean (ignores None values)
   - If all boolean flags are True and no SELL signal is active, sets:
     - `strategy["decision"] = "BUY"`
     - `signals["buy_signal"] = True`
   - This rule runs AFTER all individual BUY conditions are computed
   - Overrides any earlier WAIT decision

2. **Always Compute Reasons** (lines 312-360):
   - All `buy_*` reasons are always computed, regardless of position state
   - `buy_rsi_ok`, `buy_ma_ok`, `buy_target_ok`, `buy_volume_ok`, `buy_price_ok` are always populated
   - Position state (`last_buy_price`) does NOT block signal computation

3. **Debug Logging** (lines 671-679):
   - `[DEBUG_STRATEGY_FINAL]` log at the end of `calculate_trading_signals`
   - Logs symbol, decision, buy_signal, and all buy_* reasons

### Frontend Changes

**File**: `frontend/src/app/page.tsx`

1. **Removed Override** (lines 8582-8592):
   - Removed `hasBlockingStrategyReason()` check that was overriding backend decision
   - Frontend now trusts backend decision completely
   - Added comment: "CANONICAL: Trust backend decision completely - backend canonical rule ensures that if all buy_* flags are True, then decision=BUY. Frontend must not override."

2. **Index Calculation** (lines 1701-1714):
   - `computeStrategyIndex()` only counts boolean flags (ignores None values)
   - When all boolean flags are True, index = 100%
   - Matches backend canonical rule logic

3. **Button Color & Label** (lines 8605-8609):
   - Button color and label use `signal` variable, which comes directly from `backendDecision`
   - Green for BUY, Red for SELL, Gray for WAIT

### Monitoring Service Changes

**File**: `backend/app/services/signal_monitor.py`

1. **Debug Logging** (lines 1436-1458):
   - Added `[DEBUG_MONITOR_BUY]` log before alert evaluation
   - Logs: symbol, buy_signal, decision, alert flags, throttle status, and buy_* reasons
   - Helps diagnose why BUY alerts are or aren't sent

2. **Alert Logic** (lines 1468-1809):
   - Monitoring service correctly reads `buy_signal` from `calculate_trading_signals`
   - Checks alert flags (`alert_enabled`, `buy_alert_enabled`)
   - Checks throttle (time/price change)
   - Sends BUY alert if all conditions are met

## Data Flow

```
Backend calculate_trading_signals()
  ↓
1. Compute all buy_* reasons (always, regardless of position)
  ↓
2. Canonical rule: if all buy_* boolean flags are True → decision=BUY, buy_signal=True
  ↓
3. Return: {buy_signal, strategy: {decision, reasons}}
  ↓
Backend API /dashboard/state
  ↓
4. Include strategy_state in response
  ↓
Frontend
  ↓
5. Read backendDecision from strategyState.decision
  ↓
6. Use backendDecision directly (no override)
  ↓
7. Calculate index from buy_* reasons (only boolean flags)
  ↓
8. Display: decision label, button color, index
  ↓
Monitoring Service
  ↓
9. Read buy_signal from calculate_trading_signals
  ↓
10. Check alert flags and throttle
  ↓
11. Send BUY alert if conditions met
```

## Key Principles

1. **Backend is Source of Truth**: The backend canonical rule is the single source of truth for BUY decisions. Frontend must trust it completely.

2. **Signals ≠ Orders**: Signal computation is independent of position state. Position checks belong only in the order placement layer.

3. **None is Not Blocking**: When a reason is `None` (e.g., `buy_volume_ok=None` when volume data unavailable), it means "not applicable/not blocking". Only `False` values block the decision.

4. **Index Calculation**: The frontend index is calculated purely from backend `buy_*` reasons. When all boolean flags are True, index = 100%.

## Testing

See `backend/tests/test_trading_signals_canonical.py` for:
- Test that canonical rule triggers when all flags are True
- Test that canonical rule works even with position
- Test that one False flag prevents BUY
- Test that None flags don't block BUY

## Verification

To verify the fix is working:

1. **Backend Logs**: Check for `[DEBUG_STRATEGY_FINAL]` showing `decision=BUY buy=True` with all reasons True
2. **Frontend**: Row should show BUY (green), index = 100%, button green
3. **Monitoring**: Check `[DEBUG_MONITOR_BUY]` logs showing alert evaluation
4. **Alerts**: If alerts enabled and not throttled, BUY alert should be sent

## Files Changed

- `backend/app/services/trading_signals.py`: Canonical rule, always compute reasons, debug logging
- `frontend/src/app/page.tsx`: Remove override, trust backend decision, index calculation
- `backend/app/services/signal_monitor.py`: Debug logging for BUY alerts
- `backend/tests/test_trading_signals_canonical.py`: Tests for canonical rule
- `docs/buy_decision_alignment.md`: This documentation






