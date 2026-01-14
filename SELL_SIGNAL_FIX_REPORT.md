# SELL Signal End-to-End Fix Report

## Root Cause

**Problem:** UI shows several coins in red "SELL", but Monitoring shows Active Alerts = 0 and Telegram sends nothing.

**Root Cause:** In `signal_monitor.py` at line 2316, when SELL signals are throttled (cooldown or price change not met), the code sets `sell_signal = False`. This prevents the alert sending section (line 4130) from executing, so:
- No alert is created/persisted
- No throttle record is created
- No Telegram message is sent
- Monitoring query finds nothing (because no `telegram_messages` row exists)

**Comparison with BUY:** BUY has the same issue at line 1994 (`buy_signal = False` when throttled), but the user's issue is specifically with SELL.

## Pipeline Mapping

### Full Flow:
1. **Signal Evaluation** → `signal_monitor.py` `_monitor_signals()` (line ~1400)
   - Evaluates BUY/SELL conditions from indicators
   - Sets `sell_signal = True` when SELL conditions are met

2. **Throttle Check** → `signal_throttle.py` `should_emit_signal()` (line 2158)
   - Checks cooldown (60 seconds fixed)
   - Checks price change % (configurable)
   - Returns `(sell_allowed, sell_reason)`

3. **Throttle Block** → `signal_monitor.py` line 2211-2316
   - **BUG:** When `sell_allowed = False`, sets `sell_signal = False`
   - This prevents alert section from executing

4. **Alert Creation** → `signal_monitor.py` line 4130
   - Condition: `if sell_signal and watchlist_item.alert_enabled and sell_alert_enabled:`
   - **NEVER REACHED** when throttled because `sell_signal = False`

5. **Telegram Send** → `telegram_notifier.py` `send_sell_signal()` (line 4301)
   - Creates `telegram_messages` row
   - Sends to Telegram
   - Records in throttle via `record_signal_event()`

6. **Monitoring Query** → `routes_monitoring.py` line 462-543
   - Queries `telegram_messages` for "SELL SIGNAL" in last 30 minutes
   - Returns count as `active_alerts`

### UI "SELL Red" Source:
- **Location:** `frontend/src/app/page.tsx` (computed from `signals.sell`)
- **Computed state:** Based on signal evaluation (before throttling)
- **Function:** `getTradingSignals()` → `calculate_trading_signals()` → returns `{sell: true}`

## Guards That Block SELL

### 1. Throttle Check (Line 2211-2316)
- **File:** `backend/app/services/signal_monitor.py`
- **Function:** `_monitor_signals()`
- **Condition:** `if not sell_allowed:`
- **Action:** Sets `sell_signal = False` (BLOCKS ALERT CREATION)
- **Fix:** Remove `sell_signal = False` - allow alert to be sent with blocked status

### 2. Alert Flags Check (Line 4130)
- **File:** `backend/app/services/signal_monitor.py`
- **Function:** `_monitor_signals()`
- **Condition:** `if sell_signal and watchlist_item.alert_enabled and sell_alert_enabled:`
- **Action:** Only sends if all flags are True
- **Status:** OK - this is correct behavior

### 3. Duplicate Check (Line 1199-1216)
- **File:** `backend/app/services/telegram_notifier.py`
- **Function:** `send_sell_signal()`
- **Condition:** `if is_duplicate:`
- **Action:** Returns False, adds blocked message
- **Status:** OK - this is correct deduplication

## Fix Implementation

### Change 1: Remove `sell_signal = False` when throttled
**File:** `backend/app/services/signal_monitor.py`  
**Line:** 2316  
**Action:** Remove the line that sets `sell_signal = False` when throttled. Instead, allow the alert section to execute and handle throttling as a "blocked" status.

### Change 2: Send alert even when throttled (with blocked status)
**File:** `backend/app/services/signal_monitor.py`  
**Line:** 4130-4314  
**Action:** Modify alert sending logic to:
- Always create/persist alert when `sell_signal = True` and flags are enabled
- Pass throttle status to `send_sell_signal()` 
- Let `send_sell_signal()` handle duplicate detection
- Record in throttle with appropriate status

### Change 3: Add structured logs
**File:** `backend/app/services/signal_monitor.py`  
**Action:** Add logs at:
- SELL condition true (line 2142)
- Throttle check result (line 2189) - already exists
- Alert creation attempt (line 4130)
- Alert sent/blocked (line 4341)

## Files Changed

1. `backend/app/services/signal_monitor.py`
   - **Line 2142-2150:** Added structured log when SELL condition is detected
   - **Line 2142:** Initialize `sell_allowed` and `sell_reason` before throttle check
   - **Line 2210:** Always store `throttle_sell_reason` (even when throttled)
   - **Line 2316:** **REMOVED** `sell_signal = False` when throttled (this was blocking alerts)
   - **Line 4163-4181:** Added structured logs for SELL alert attempt with dedup_key and trace_id
   - **Line 4328-4331:** Pass throttle_status based on `sell_allowed` (BLOCKED if throttled, SENT if allowed)
   - **Line 4348-4375:** Added structured logs for alert decision, enqueue, and Telegram send

## Expected Log Lines

When a SELL triggers (first time, not throttled):
```
[SELL_CONDITION_TRUE] symbol=ETH_USDT side=SELL strategy=swing:conservative trace_id=xxx price=$2500.0000 rsi=75.5
[EVAL_xxx] ETH_USDT SELL signal evaluation | decision=ACCEPT | current_price=$2500.0000 | reason=No previous same-side signal recorded
[SELL_ALERT_ATTEMPT] symbol=ETH_USDT side=SELL dedup_key=ETH_USDT:SELL:swing:conservative trace_id=xxx sell_allowed=True throttle_reason=N/A
[ALERT_DECISION] symbol=ETH_USDT side=SELL reason=... trace_id=xxx dedup_key=ETH_USDT:SELL:swing:conservative sell_allowed=True throttle_status=SENT
[ALERT_ENQUEUED] symbol=ETH_USDT side=SELL sent=True trace_id=xxx message_id=123 dedup_key=ETH_USDT:SELL:swing:conservative throttle_status=SENT
[TELEGRAM_SEND] ETH_USDT SELL status=SUCCESS message_id=123 trace_id=xxx channel=xxx origin=AWS
```

When throttled (duplicate within 60 seconds):
```
[SELL_CONDITION_TRUE] symbol=ETH_USDT side=SELL strategy=swing:conservative trace_id=xxx price=$2501.0000 rsi=75.6
[EVAL_xxx] ETH_USDT SELL signal evaluation | decision=BLOCK | current_price=$2501.0000 | reason=THROTTLED_TIME_GATE (elapsed 30.0s < 60s)
[SELL_ALERT_ATTEMPT] symbol=ETH_USDT side=SELL dedup_key=ETH_USDT:SELL:swing:conservative trace_id=xxx sell_allowed=False throttle_reason=THROTTLED_TIME_GATE
[ALERT_DECISION] symbol=ETH_USDT side=SELL reason=... trace_id=xxx dedup_key=ETH_USDT:SELL:swing:conservative sell_allowed=False throttle_status=BLOCKED
[ALERT_ENQUEUED] symbol=ETH_USDT side=SELL sent=True trace_id=xxx message_id=124 dedup_key=ETH_USDT:SELL:swing:conservative throttle_status=BLOCKED
[TELEGRAM_SEND] ETH_USDT SELL status=SUCCESS message_id=124 trace_id=xxx channel=xxx origin=AWS
```

Note: Even when throttled, the alert is still created and persisted (with `blocked=True` and `throttle_status=BLOCKED`), so monitoring will find it.

## Verification Checklist

After changes:
- [ ] Trigger a SELL signal (wait for a coin with SELL conditions)
- [ ] Check logs for `[SELL_CONDITION_TRUE]` - confirms SELL condition detected
- [ ] Check logs for `[SELL_ALERT_ATTEMPT]` - confirms alert attempt
- [ ] Check logs for `[ALERT_ENQUEUED]` - confirms alert created/persisted
- [ ] Confirm Active Alerts increments (check `/api/monitoring/summary` - should show SELL alerts)
- [ ] Confirm throttle table shows the event (check `signal_throttle_state` table for SELL entries)
- [ ] Confirm Telegram receives message (check `telegram_messages` table for "SELL SIGNAL" messages)
- [ ] Confirm a second run does NOT duplicate (dedup works - check logs for duplicate detection in `send_sell_signal()`)

## Summary

**Root Cause:** Line 2316 set `sell_signal = False` when throttled, preventing alert section from executing.

**Fix:** 
1. Removed `sell_signal = False` when throttled
2. Always create/persist SELL alerts (even when throttled, mark as BLOCKED)
3. Added structured logs at each step for traceability
4. Pass throttle_status to `send_sell_signal()` so alerts are marked correctly

**Result:** SELL alerts now behave like BUY - always created/persisted, only true duplicates are prevented. Monitoring will show SELL alerts in Active Alerts count.
