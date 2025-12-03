# SELL Alert Pipeline Fix

## Summary

Fixed a critical bug where SELL alerts were not being emitted because the SELL alert emission block was incorrectly nested inside the BUY alert emission block. This meant SELL alerts would only be processed when a BUY signal was also present.

## Original Bug

The SELL alert emission code (lines ~2398-2684) was nested inside the BUY alert emission block, causing it to only execute when `buy_signal and buy_flag_allowed` was True. This prevented independent SELL alerts from being emitted.

## Fix Applied

### 1. Structural Change
- **Moved SELL block to same level as BUY block**: The SELL alert emission block is now a sibling of the BUY block, not nested inside it.
- **Correct indentation**: Fixed indentation so SELL block is at the same level as BUY block (8 spaces, not 12).

### 2. Throttle Logic
- **Initialized variables**: Added initialization of `sell_allowed` and `sell_reason` before throttle check to ensure they're always defined.
- **Throttle check**: The throttle check happens at lines 1203-1211, setting `sell_allowed` and `sell_reason`.
- **Condition check**: SELL emission now checks `if sell_signal and sell_allowed and sell_flag_allowed:` to ensure:
  - SELL signal is detected
  - Throttle allows emission
  - Alert flags allow emission

### 3. Comprehensive Logging
Added the following log markers for SELL alerts:

- **`[LIVE_SELL_DECISION]`**: Logged when a SELL signal is detected, showing decision, flags, and origin.
- **`[LIVE_SELL_THROTTLE]`**: Logged when throttle is evaluated, showing `can_emit_sell` and reason.
- **`[LIVE_SELL_CALL]`**: Logged just before calling `telegram_notifier.send_sell_signal()`.
- **`[LIVE_SELL_GATEKEEPER]`**: Logged in `telegram_notifier.send_message()` for SELL alerts (if message contains "SELL SIGNAL").
- **`[ALERT_EMIT_FINAL]`**: Logged after alert emission attempt, showing:
  - `side=SELL`
  - `status=SENT` (if sent) or `status=telegram_api_failed` (if Telegram API failed)
  - `throttle_status` and `throttle_reason`
- **`[LIVE_SELL_MONITORING]`**: Logged when Monitoring entry is created, showing `blocked` status and throttle info.

### 4. Monitoring Registration
- **Sent alerts**: Registered with `blocked=False` and `throttle_status=SENT`.
- **Blocked alerts**: Registered with `blocked=True` and `throttle_status=BLOCKED` (when throttled or flags disabled).

## Code Structure (After Fix)

```python
# BUY block -----------------------------
if buy_signal and buy_flag_allowed:
    # ... BUY alert emission logic ...

# SELL block ----------------------------
# CRITICAL: This is now at the SAME level as BUY, not nested inside it
if sell_signal and sell_allowed and sell_flag_allowed:
    # ... SELL alert emission logic ...
    # - Lock mechanism
    # - Final flag verification
    # - Call telegram_notifier.send_sell_signal()
    # - Register in Monitoring
    # - Create SELL order if trade_enabled
```

## Verification

### Commands to Verify SELL Alerts

1. **Check debug script output**:
   ```bash
   docker compose exec backend-aws bash -c 'cd /app && python scripts/debug_live_signals_all.py'
   ```
   Should show:
   - `SELL_SIGNALS_NOW: [list of symbols]`
   - `Symbols that can emit SELL alert: N`

2. **Check logs for SELL markers**:
   ```bash
   docker compose logs -f backend-aws | grep -E 'LIVE_SELL|ALERT_EMIT_FINAL.*SELL'
   ```
   Should show:
   - `[LIVE_SELL_DECISION]` entries
   - `[LIVE_SELL_THROTTLE]` entries
   - `[LIVE_SELL_CALL]` entries
   - `[ALERT_EMIT_FINAL] side=SELL` entries

3. **Check Monitoring tab**:
   - Should show new rows for SELL alerts
   - `blocked=false` for sent alerts
   - `blocked=true` for throttled/blocked alerts

4. **Check Telegram**:
   - Should receive SELL alerts with `[AWS]` prefix (when running on AWS)

## Files Modified

- `backend/app/services/signal_monitor.py`:
  - Moved SELL alert emission block outside BUY block
  - Fixed indentation
  - Added comprehensive logging
  - Ensured throttle check is properly used
  - Ensured Monitoring registration for both sent and blocked alerts

## Success Criteria

After this fix:
- ✅ SELL alerts fire independently of BUY alerts
- ✅ SELL throttle works correctly
- ✅ SELL alerts reach Telegram (when origin=AWS) and Monitoring
- ✅ `debug_live_signals_all.py` shows SELL alerts as eligible
- ✅ System logs `[LIVE_SELL_CALL]` and `[ALERT_EMIT_FINAL side=SELL]`
- ✅ Monitoring tab shows SELL rows with correct `blocked` status

## Date

Fixed: 2025-01-27

