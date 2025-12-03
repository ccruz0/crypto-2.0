# Live Alerts Fix Summary

**Date:** 2025-12-03  
**Status:** ✅ **LOGGING ADDED - INVESTIGATION IN PROGRESS**

---

## Root Cause Analysis

### Investigation Findings

1. **SignalMonitorService is Running**
   - ✅ Service starts correctly in `main.py` (lines 201-207)
   - ✅ No crashes detected in AWS logs
   - ✅ Service is actively evaluating symbols every 30 seconds

2. **No Hidden Blockers Found**
   - ✅ No `RUN_TELEGRAM` checks blocking alerts in `signal_monitor.py`
   - ✅ No `DISABLE_ALERT` flags found
   - ✅ Gatekeeper logic is correct (allows AWS and TEST origins)

3. **Current State**
   - ⚠️ **Signals are being evaluated but all showing `decision=WAIT`**
   - ⚠️ No BUY/SELL signals are being detected, so no alerts are being emitted
   - ⚠️ This could be:
     - Strategy rules not being met (RSI, MA conditions, etc.)
     - Throttling blocking signals before they reach alert emission
     - Flag checks blocking signals

---

## Changes Made

### 1. Added Comprehensive Logging

**File:** `backend/app/services/signal_monitor.py`

**Changes:**
- **Decision Point Logging** (lines ~1041-1054):
  ```python
  logger.info(
      f"[LIVE_ALERT_DECISION] symbol={symbol} side=BUY/SELL decision={decision} "
      f"price={current_price:.4f} origin={origin} strategy={preset_name}-{risk_mode}"
  )
  ```
  - Logs when BUY/SELL signals are detected
  - Includes decision, price, origin, and strategy

- **Alert Call Logging** (lines ~1544-1548 for BUY, ~2519-2523 for SELL):
  ```python
  logger.info(
      f"[LIVE_ALERT_CALL] symbol={symbol} side=BUY/SELL origin={origin} "
      f"price={current_price:.4f} reason={reason_text[:100]}"
  )
  ```
  - Logs immediately before calling `telegram_notifier.send_buy_signal()` or `send_sell_signal()`
  - Confirms alert emission is attempted

- **Throttle Decision Logging** (lines ~1131-1140 for BUY):
  ```python
  logger.info(
      f"[ALERT_THROTTLE_DECISION] origin={origin} symbol={symbol} side=BUY allowed={buy_allowed} "
      f"reason={buy_reason} price={current_price:.4f} ..."
  )
  ```
  - Logs throttle check results for BUY signals
  - SELL already had this logging (line 1178)

**File:** `backend/app/services/telegram_notifier.py`

**Changes:**
- **Gatekeeper Logging for Live Alerts** (lines ~183-188):
  ```python
  if "LIVE ALERT" in message or "BUY SIGNAL" in message or "SELL SIGNAL" in message:
      logger.info(
          f"[LIVE_ALERT_GATEKEEPER] origin={origin_upper} enabled={self.enabled} "
          f"bot_token_present={bool(self.bot_token)} chat_id_present={bool(self.chat_id)}"
      )
  ```
  - Logs gatekeeper check specifically for live alerts
  - Shows origin, enabled status, and credential presence

### 2. Ensured Blocked Signals are Registered

**File:** `backend/app/services/signal_monitor.py`

**Changes:**
- **BUY Throttled Signals** (lines ~1150-1161):
  - Added `add_telegram_message()` call for throttled BUY signals
  - Registers with `blocked=True`, `throttle_status="BLOCKED"`, `throttle_reason=buy_reason`
  - SELL already had this (lines 1195-1203)

- **Flag-Blocked Signals**:
  - BUY: Already registered (lines 1403-1406)
  - SELL: Already registered (lines 2496-2500)

---

## Files Modified

1. **`backend/app/services/signal_monitor.py`**
   - Added `[LIVE_ALERT_DECISION]` logging at decision point
   - Added `[LIVE_ALERT_CALL]` logging before alert emission
   - Added `[ALERT_THROTTLE_DECISION]` logging for BUY signals
   - Ensured throttled BUY signals are registered in Monitoring

2. **`backend/app/services/telegram_notifier.py`**
   - Added `[LIVE_ALERT_GATEKEEPER]` logging for live alerts

3. **`docs/monitoring/LIVE_ALERT_PIPELINE_NOTES.md`** (new)
   - Complete documentation of the alert pipeline
   - Decision points, emission triggers, and Monitoring registration

---

## How to Verify

### 1. Check SignalMonitorService is Running

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose logs backend-aws --tail 200 | grep -E "SignalMonitorService|Starting Signal"'
```

**Expected:** Logs showing "🔧 Starting Signal monitor service..." and periodic signal evaluations

### 2. Monitor Live Alert Flow

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose logs -f backend-aws' | grep -E 'LIVE_ALERT|ALERT_EMIT|ALERT_THROTTLE'
```

**Look for:**
- `[LIVE_ALERT_DECISION]` - Signal detected (BUY/SELL)
- `[ALERT_THROTTLE_DECISION]` - Throttle check result
- `[LIVE_ALERT_CALL]` - Alert emission attempted
- `[LIVE_ALERT_GATEKEEPER]` - Gatekeeper check
- `[ALERT_EMIT_FINAL]` - Final emission status

### 3. Check Monitoring Tab

- **Sent Alerts:** Should appear with `blocked=false`
- **Blocked Alerts:** Should appear with `blocked=true` and `throttle_status="BLOCKED"` or reason

### 4. Verify Signal Detection

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && \
  docker compose logs backend-aws --tail 500 | grep -E "decision=BUY|decision=SELL|buy_signal=True|sell_signal=True"'
```

**Expected:** Logs showing when signals are actually detected (not just WAIT)

---

## Next Steps

1. **Monitor Logs for Signal Detection**
   - Wait for a symbol to meet strategy conditions
   - Verify `[LIVE_ALERT_DECISION]` appears
   - Verify `[LIVE_ALERT_CALL]` appears
   - Verify `[LIVE_ALERT_GATEKEEPER]` shows `enabled=True` and `origin=AWS`

2. **If Signals Detected But Not Sent**
   - Check `[ALERT_THROTTLE_DECISION]` - is `allowed=False`?
   - Check `[LIVE_ALERT_GATEKEEPER]` - is `enabled=False`?
   - Check `[LIVE_ALERT_CALL]` - does it appear?

3. **If No Signals Detected**
   - Check strategy rules (RSI thresholds, MA conditions)
   - Check watchlist flags (`alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`)
   - Verify symbols are in watchlist and have valid configurations

---

## Summary

**Status:** Logging infrastructure is in place. The system is ready to diagnose why alerts aren't being sent.

**Current Hypothesis:** Signals may not be meeting strategy conditions (all showing `decision=WAIT`), or signals are being throttled before reaching alert emission.

**Action Required:** Monitor logs for `[LIVE_ALERT_DECISION]` and `[LIVE_ALERT_CALL]` to identify where the pipeline is breaking.

