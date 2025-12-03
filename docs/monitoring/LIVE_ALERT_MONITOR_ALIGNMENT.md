# Live Alert Monitor Alignment

## Overview

The live `SignalMonitorService` in `backend-aws` now uses **exactly the same decision logic** as `backend/scripts/debug_live_signals_all.py`. This ensures that when the debug script reports a BUY/SELL signal, the live monitor will emit the corresponding alert.

## Single Source of Truth

The decision logic is implemented identically in both places:

1. **Signal Calculation**: Both call `calculate_trading_signals()` with the same parameters
2. **Decision Determination**: Both use:
   - `decision = "BUY"` if `buy_signal == True`
   - `decision = "SELL"` if `sell_signal == True`
   - `decision = "WAIT"` otherwise
3. **Throttle Check**: Both call `should_emit_signal()` for BUY and SELL separately
4. **Can Emit Logic**: Both compute:
   - `can_emit_buy_alert = buy_allowed AND buy_alert_enabled AND alert_enabled`
   - `can_emit_sell_alert = sell_allowed AND sell_alert_enabled AND alert_enabled`

## Running the Debug Script

To see which symbols currently have BUY/SELL signals:

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py"'
```

The script outputs:
- A table showing each symbol's decision, flags, and throttle status
- Summary: `BUY_SIGNALS_NOW: [...]` and `SELL_SIGNALS_NOW: [...]`
- Count of symbols that can emit alerts

## Interpreting Live Logs

### Primary Decision Log

**`[LIVE_ALERT_DECISION]`** - Logged once per symbol per cycle, ALWAYS (even for WAIT):

```
[LIVE_ALERT_DECISION] symbol=ALGO_USDT | preset=scalp-Conservative | decision=SELL | 
buy_signal=False | sell_signal=True | alert_enabled=True | buy_alert_enabled=True | 
sell_alert_enabled=True | trade_enabled=False | can_emit_buy=False | can_emit_sell=True | 
buy_throttle_status=N/A | sell_throttle_status=SENT | volume_ratio=0.5405 | 
min_volume_ratio=0.3000 | origin=AWS
```

**Fields:**
- `decision`: BUY/SELL/WAIT (matches debug script)
- `buy_signal` / `sell_signal`: Boolean from `calculate_trading_signals()`
- `alert_enabled` / `buy_alert_enabled` / `sell_alert_enabled`: Watchlist flags
- `can_emit_buy` / `can_emit_sell`: Final decision (throttle AND flags)
- `buy_throttle_status` / `sell_throttle_status`: SENT/BLOCKED/N/A
- `volume_ratio` / `min_volume_ratio`: Volume metrics

### Alert Emission Logs

**`[LIVE_BUY_CALL]`** / **`[LIVE_SELL_CALL]`** - When alert is about to be sent:

```
[LIVE_SELL_CALL] symbol=ALGO_USDT can_emit=True throttle_status=SENT 
sell_alert_enabled=True alert_enabled=True
```

**`[LIVE_BUY_SKIPPED]`** / **`[LIVE_SELL_SKIPPED]`** - When alert is NOT sent (with reason):

```
[LIVE_SELL_SKIPPED] symbol=ALGO_USDT reason=throttled (Price change < 1%) 
sell_signal=True sell_allowed=False sell_flag_allowed=True
```

**`[LIVE_ALERT_GATEKEEPER]`** - Gatekeeper check in `telegram_notifier`:

```
[LIVE_ALERT_GATEKEEPER] symbol=ALGO_USDT side=SELL origin=AWS enabled=True 
bot_token_present=True chat_id_present=True allowed=True
```

**`[ALERT_EMIT_FINAL]`** - Final status after emission attempt:

```
[ALERT_EMIT_FINAL] side=SELL symbol=ALGO_USDT origin=AWS sent=True blocked=False 
throttle_status=SENT throttle_reason=Allowed by cooldown and price change 
monitoring_saved=True
```

## Typical Failure Modes

### 1. No Signal Detected
**Symptom**: `[LIVE_ALERT_DECISION]` shows `decision=WAIT`, `buy_signal=False`, `sell_signal=False`

**Cause**: Trading conditions not met (RSI, MA, volume, etc.)

**Action**: Check indicators in debug script output

### 2. Signal Detected but Throttled
**Symptom**: `decision=SELL`, `sell_signal=True`, `can_emit_sell=False`, `sell_throttle_status=BLOCKED`

**Cause**: Cooldown period or insufficient price change

**Action**: Wait for cooldown or price change threshold

**Logs**: `[LIVE_SELL_SKIPPED] reason=throttled (...)`

### 3. Signal Detected but Flags Disabled
**Symptom**: `decision=SELL`, `sell_signal=True`, `can_emit_sell=False`, `sell_alert_enabled=False`

**Cause**: Alert flags disabled in watchlist

**Action**: Enable `alert_enabled` and `sell_alert_enabled` in dashboard

**Logs**: `[LIVE_SELL_SKIPPED] reason=alert_enabled=False` or `sell_alert_enabled=False`

### 4. Gatekeeper Blocked
**Symptom**: `[LIVE_ALERT_GATEKEEPER] allowed=False`

**Cause**: Origin is not AWS/TEST, or Telegram disabled

**Action**: Check `RUNTIME_ORIGIN` env var, check `RUN_TELEGRAM` setting

### 5. Telegram API Failure
**Symptom**: `[ALERT_EMIT_FINAL] sent=False error=telegram_api_failed`, but `monitoring_saved=True`

**Cause**: Telegram API error (network, credentials, rate limit)

**Action**: Check Telegram credentials, network connectivity

**Note**: Monitoring entry is still created even if Telegram fails

### 6. Monitoring Registration Failed
**Symptom**: `[ALERT_EMIT_FINAL] monitoring_saved=False`

**Cause**: Database error or monitoring service unavailable

**Action**: Check database connectivity, check monitoring service logs

## Debugging Procedure

### Step 1: Check Debug Script Output

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py"'
```

Look for:
- `SELL_SIGNALS_NOW: ['ALGO_USDT', 'TON_USDT']`
- Symbols with `can_emit_sell=True` in the table

### Step 2: Check Live Monitor Logs

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 0 | grep -E "LIVE_ALERT_DECISION|LIVE_BUY_CALL|LIVE_SELL_CALL|ALERT_EMIT_FINAL"
```

Look for:
- `[LIVE_ALERT_DECISION]` entries for the same symbols
- `decision=SELL` matching debug script
- `can_emit_sell=True` matching debug script
- `[LIVE_SELL_CALL]` for symbols that should emit
- `[ALERT_EMIT_FINAL] side=SELL sent=True` for successful sends

### Step 3: Compare Debug Script vs Live Monitor

For each symbol in `SELL_SIGNALS_NOW`:

1. **Debug Script**: Check `can_emit_sell=True` and `throttle_sell_status=SENT`
2. **Live Monitor**: Check `[LIVE_ALERT_DECISION]` shows:
   - `decision=SELL`
   - `sell_signal=True`
   - `can_emit_sell=True`
   - `sell_throttle_status=SENT`

If they don't match, check:
- Timing differences (throttle state may change between runs)
- Flag changes (watchlist flags may have changed)
- Indicator differences (cached vs fresh data)

### Step 4: Verify Telegram and Monitoring

1. **Telegram**: Check for messages with `[AWS]` prefix
2. **Monitoring Tab**: Check for new rows with:
   - `symbol` matching the alert
   - `blocked=false` for sent alerts
   - `blocked=true` for throttled alerts

## Key Log Markers

| Marker | When | Purpose |
|--------|------|---------|
| `[LIVE_ALERT_DECISION]` | Every symbol, every cycle | Show decision and all flags |
| `[LIVE_BUY_CALL]` | Before sending BUY alert | Confirm alert will be sent |
| `[LIVE_SELL_CALL]` | Before sending SELL alert | Confirm alert will be sent |
| `[LIVE_BUY_SKIPPED]` | BUY signal but not sent | Explain why not sent |
| `[LIVE_SELL_SKIPPED]` | SELL signal but not sent | Explain why not sent |
| `[LIVE_ALERT_GATEKEEPER]` | In telegram_notifier | Show gatekeeper decision |
| `[ALERT_EMIT_FINAL]` | After emission attempt | Final status (sent, blocked, error) |

## Files Modified

- `backend/app/services/signal_monitor.py`: Main monitor logic with comprehensive logging
- `backend/app/services/telegram_notifier.py`: Enhanced gatekeeper logging
- `backend/scripts/debug_live_signals_all.py`: Reference implementation (unchanged)

## Date

Last Updated: 2025-01-27

