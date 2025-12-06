# ADA SELL Alert Fix Summary

**Date:** 2025-12-02  
**Issue:** SELL signals appear in Watchlist UI but SELL alerts are not always sent from AWS  
**Status:** ✅ Fixed

---

## Problem Statement

User reported:
- SELL signals for ADA (ADA_USDT / ADA_USD) appear in Watchlist UI
- But corresponding SELL alerts are not always received in Telegram
- Sometimes "LOCAL" alerts appear instead, which don't respect throttle rules

---

## Root Cause

### Primary Issue: Redundant Throttle Check

SELL alerts were being **double-throttled**:

1. **Early throttle check** (lines 1173-1211):
   - Uses `should_emit_signal()` from `signal_throttle.py`
   - Checks database (`SignalThrottleState` table)
   - If throttled → sets `sell_signal = False`
   - ✅ **Correct and necessary**

2. **Late throttle check** (lines 2442-2449):
   - Uses `should_send_alert()` (instance method)
   - Checks in-memory `self.last_alert_states` dictionary
   - ❌ **Redundant and problematic**
   - In-memory state can be out of sync with database
   - Can cause alerts to be blocked even when early check passed

### Secondary Issue: Inconsistent Logging

- Throttle decisions were not always logged with origin (AWS vs LOCAL)
- Missing context: last price, last time used for comparison
- Made debugging difficult

---

## Fixes Applied

### 1. Removed Redundant Throttle Check for SELL

**File:** `backend/app/services/signal_monitor.py`

**Change:**
- Removed `should_send_alert()` call for SELL alerts (line 2442-2449)
- Set `should_send = True` directly (early throttle already passed)
- Kept lock mechanism for race condition prevention

**Before:**
```python
should_send, throttle_reason = self.should_send_alert(
    symbol=symbol,
    side="SELL",
    current_price=current_price,
    ...
)
if not should_send:
    # Block alert
```

**After:**
```python
# CRITICAL: Throttling was already checked earlier using should_emit_signal() (database-based)
# At this point, if sell_signal=True, it means throttle passed. We should send the alert.
should_send = True  # Early throttle already passed, so we should send
throttle_reason = "Early throttle check passed (database-based)"
```

### 2. Removed Redundant Throttle Check for BUY (Legacy Path)

**File:** `backend/app/services/signal_monitor.py`

**Change:**
- Removed `should_send_alert()` call for BUY alerts in legacy path (line 1954-1973)
- Same fix as SELL: early throttle check is sufficient

### 3. Enhanced Throttle Decision Logging

**File:** `backend/app/services/signal_monitor.py`

**Change:**
- Added comprehensive logging for ALL throttle decisions (both BUY and SELL)
- Includes: `origin`, `symbol`, `side`, `allowed`, `reason`, `price`, `last_price`, `last_time`

**Before:**
```python
if not sell_allowed:
    logger.info(f"[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side=SELL allowed=False ...")
```

**After:**
```python
origin = get_runtime_origin()
logger.info(
    f"[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side=SELL allowed={sell_allowed} "
    f"reason={sell_reason} price={current_price:.4f} "
    f"last_sell_price={last_sell_snapshot.price if last_sell_snapshot else None} "
    f"last_sell_time={last_sell_snapshot.timestamp.isoformat() if last_sell_snapshot and last_sell_snapshot.timestamp else None}"
)
```

### 4. Added Origin Logging to ALERT_EMIT_FINAL

**File:** `backend/app/services/signal_monitor.py`

**Change:**
- Added `origin` to `[ALERT_EMIT_FINAL]` logs for both BUY and SELL
- Helps identify if alerts are coming from AWS or LOCAL

**Before:**
```python
logger.info(f"[ALERT_EMIT_FINAL] symbol={symbol} | side=SELL | status=success | ...")
```

**After:**
```python
origin = get_runtime_origin()
logger.info(
    f"[ALERT_EMIT_FINAL] origin={origin} symbol={symbol} | side=SELL | status=success | ..."
)
```

---

## Code Diffs

### Key Changes in `signal_monitor.py`

1. **Lines 1127-1133 (BUY throttle logging):**
   - Moved `get_runtime_origin()` call before the `if not buy_allowed` check
   - Added comprehensive logging with last price/time

2. **Lines 1184-1191 (SELL throttle logging):**
   - Same enhancement as BUY
   - Logs throttle decision with full context

3. **Lines 1954-1973 (BUY legacy path):**
   - Removed redundant `should_send_alert()` call
   - Set `should_send = True` directly

4. **Lines 2442-2449 (SELL alert path):**
   - Removed redundant `should_send_alert()` call
   - Set `should_send = True` directly

5. **Lines 2534-2537 (SELL ALERT_EMIT_FINAL):**
   - Added `origin` to log message

6. **Lines 2207-2209 (BUY legacy ALERT_EMIT_FINAL):**
   - Added `origin` to log message

---

## Behavior Explanation

### What Happens When a First SELL Signal Appears

**Example:** ADA_USDT, price = $0.50, RSI = 75, decision = SELL

1. **Strategy Engine:** `calculate_trading_signals()` returns `sell_signal=True`
2. **Early Throttle Check:** `should_emit_signal()` checks database
   - No previous SELL → `allowed=True`, `reason="No previous same-side signal recorded"`
3. **Alert Flag Check:** `sell_alert_enabled=True` → proceed
4. **Alert Sent:** `telegram_notifier.send_sell_signal()` called
5. **State Recorded:** `record_signal_event()` saves to database
6. **Log:** `[ALERT_EMIT_FINAL] origin=AWS symbol=ADA_USDT side=SELL status=success`

**Result:** ✅ Alert sent to Telegram

### What Happens When a Second SELL Signal Appears Soon After

**Example:** ADA_USDT, price = $0.501, RSI = 75, decision = SELL (2 minutes after first)

1. **Strategy Engine:** `calculate_trading_signals()` returns `sell_signal=True`
2. **Early Throttle Check:** `should_emit_signal()` checks database
   - Last SELL: 2 minutes ago, price = $0.50
   - Cooldown: 2 min < 5 min → `cooldown_met = False`
   - Price change: 0.2% < 1% → `price_met = False`
   - **Both fail** → `allowed=False`, `reason="THROTTLED_MIN_TIME (elapsed 2.00m < 5.00m)"`
3. **Signal Blocked:** `sell_signal = False` (set to False)
4. **Alert NOT Sent:** Code never reaches `send_sell_signal()`
5. **Log:** `[ALERT_THROTTLE_DECISION] origin=AWS symbol=ADA_USDT side=SELL allowed=False reason=...`
6. **Monitoring:** Blocked message registered: `🚫 BLOQUEADO: ADA_USDT SELL - THROTTLED_MIN_TIME...`

**Result:** ❌ Alert NOT sent (correctly throttled)

### What Happens When a Third SELL Signal Appears After Cooldown and Price Change

**Example:** ADA_USDT, price = $0.52, RSI = 75, decision = SELL (10 minutes after first, 2% price change)

1. **Strategy Engine:** `calculate_trading_signals()` returns `sell_signal=True`
2. **Early Throttle Check:** `should_emit_signal()` checks database
   - Last SELL: 10 minutes ago, price = $0.50
   - Cooldown: 10 min >= 5 min → `cooldown_met = True` ✅
   - Price change: 4% >= 1% → `price_met = True` ✅
   - **Both pass** → `allowed=True`, `reason="Δt=10.00m>= 5.00m; Δp=4.00%>= 1.00%"`
3. **Alert Flag Check:** `sell_alert_enabled=True` → proceed
4. **Alert Sent:** `telegram_notifier.send_sell_signal()` called
5. **State Recorded:** `record_signal_event()` updates database
6. **Log:** `[ALERT_EMIT_FINAL] origin=AWS symbol=ADA_USDT side=SELL status=success`

**Result:** ✅ Alert sent to Telegram

---

## LOCAL vs AWS Alerts

### How They Differ Now

**AWS Alerts:**
- Sent to production Telegram channel
- Prefixed with `[AWS]`
- Throttle state in database (persistent)
- Respects all throttle rules

**LOCAL Alerts:**
- **Blocked** from Telegram (runtime guard)
- Logged as `[TG_LOCAL_DEBUG]`
- Still respects throttle rules in logs
- Dashboard shows `[LOCAL DEBUG]` prefix

**Key Point:** LOCAL alerts **cannot bypass throttle**. Even though they don't reach Telegram, throttle decisions are still logged with `origin=LOCAL` for debugging consistency.

**Who Sends LOCAL Alerts:**
- Any script running on Mac with `RUNTIME_ORIGIN=LOCAL` (or unset, defaults to LOCAL)
- These are blocked by the runtime guard in `telegram_notifier.send_message()`
- They appear in Monitoring UI with `[LOCAL DEBUG]` prefix for debugging

---

## Testing

### Tests Added

**File:** `backend/tests/test_ada_sell_alert_flow.py`

**Coverage:**
1. ✅ First SELL alert always allowed
2. ✅ SELL alert throttled by cooldown
3. ✅ SELL alert throttled by price change
4. ✅ SELL alert allowed after cooldown and price change
5. ✅ SELL after BUY resets throttle (direction change)
6. ✅ Throttle decision logs origin

**Run tests:**
```bash
cd /Users/carloscruz/automated-trading-platform/backend
poetry run pytest tests/test_ada_sell_alert_flow.py -v
```

**Result:** ✅ All tests pass

---

## Verification Steps

### 1. Check Throttle State for ADA

```bash
bash scripts/debug_ada_sell_alerts_remote.sh
```

### 2. Monitor Logs for Throttle Decisions

```bash
bash scripts/aws_backend_logs.sh --tail 2000 | grep 'ADA_USDT.*ALERT_THROTTLE_DECISION.*SELL'
```

**Expected output:**
- `allowed=True` when throttle passes → alert sent
- `allowed=False` when throttle blocks → alert not sent, reason shown

### 3. Verify Alerts Are Sent When Throttle Allows

```bash
bash scripts/aws_backend_logs.sh --tail 2000 | grep 'ADA_USDT.*ALERT_EMIT_FINAL.*SELL'
```

**Expected:** `[ALERT_EMIT_FINAL] origin=AWS symbol=ADA_USDT side=SELL status=success`

### 4. Check Monitoring UI

- Go to Monitoring → Telegram Messages
- Filter for ADA_USDT
- Verify:
  - Alerts appear when throttle allows
  - Blocked messages show throttle reason
  - No "LOCAL" alerts from AWS runtime

---

## Summary

✅ **Fixed:** Removed redundant throttle check that was causing double-throttling  
✅ **Enhanced:** Added comprehensive logging for throttle decisions  
✅ **Verified:** BUY and SELL use same throttle logic (database-based)  
✅ **Documented:** Created debug script and analysis document  
✅ **Tested:** Added tests for SELL alert flow

**Result:** SELL alerts now work correctly. When throttle allows, alerts are sent. When throttle blocks, clear logging explains why.






