# Alert Pipeline Debug Guide

This document explains how to debug the alert pipeline to trace BUY/SELL signals from strategy decision through to Telegram delivery.

## Pipeline Overview

The alert pipeline consists of 4 main layers:

1. **Strategy Layer** → Generates trading signals (BUY/SELL)
2. **Monitor Layer** → Evaluates signals and applies business rules (cooldowns, exposure, volume)
3. **Alert Helper Layer** → Central emission point (DB + Telegram)
4. **Telegram Delivery Layer** → HTTP API calls to Telegram

```
Strategy → Monitor → Alert Helper (DB + Telegram) → Telegram Delivery
```

## Log Tags Reference

### Strategy Layer
- `[DEBUG_STRATEGY_FINAL]` - Final strategy decision with buy_signal/sell_signal flags

### Monitor Layer
- `SignalMonitor: evaluating symbol=...` - Monitor evaluation start
- `[DEBUG_SIGNAL_MONITOR]` - Detailed monitor decisions

### Alert Helper Layer
- `[ALERT_DECISION]` - Alert emission decision logged (includes symbol, side, reason, context)
- `[ALERT_SKIP]` - Alert skipped (dry run or other reason)
- `[ALERT_ENQUEUED]` - Alert successfully enqueued/sent

### Telegram Delivery Layer
- `[TELEGRAM_SEND]` - Telegram send attempt (includes symbol, side, chat_id)
- `[TELEGRAM_ERROR]` - Telegram API error (includes status code and error body)

## Debug Workflow

### Step 1: Run the Remote Debug Script

From your Mac, run:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_alert_pipeline_remote.sh TON_USDT 30
```

This script will:
- Fetch logs from the AWS backend for the specified symbol
- Show logs from the last N minutes (default: 30)
- Group output into 4 clear sections:
  1. Strategy logs (DEBUG_STRATEGY_FINAL)
  2. Signal Monitor logs
  3. Alert pipeline logs (ALERT_*)
  4. Telegram logs (TELEGRAM_*)

### Step 2: Read the Logs

#### Check Strategy Layer
Look for `[DEBUG_STRATEGY_FINAL]` entries:
- Check if `buy_signal=True` or `sell_signal=True`
- Verify the decision matches your expectations

#### Check Monitor Layer
Look for `SignalMonitor` entries:
- Check if the monitor accepted or rejected the signal
- Look for cooldown/exposure/volume checks

#### Check Alert Helper Layer
Look for `[ALERT_DECISION]` entries:
- This confirms the alert was decided to be emitted
- Check the context (preset, risk, etc.)

Look for `[ALERT_SKIP]` entries:
- If present, the alert was skipped (dry run or other reason)
- Check the reason field

Look for `[ALERT_ENQUEUED]` entries:
- This confirms the alert was sent to Telegram
- Check the `sent` field (True/False)

#### Check Telegram Delivery Layer
Look for `[TELEGRAM_SEND]` entries:
- This confirms a Telegram API call was attempted
- Check symbol, side, and chat_id

Look for `[TELEGRAM_ERROR]` entries:
- If present, the Telegram API call failed
- Check status code and error body for details

### Step 3: Cross-Check with Monitoring API (Optional)

From your Mac, check the monitoring API to see if alerts were saved to the database:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/debug_monitoring_api_local.sh
```

This will show the last 40 entries from the Telegram messages monitoring table.

## Common Issues and Solutions

### Issue: Strategy shows buy_signal=True but no alert emitted

**Check:**
1. Monitor logs - was the signal accepted or rejected?
2. Alert helper logs - is there an `[ALERT_DECISION]` entry?
3. If `[ALERT_SKIP]` appears, check the reason (dry run, etc.)

### Issue: Alert shows `[ALERT_ENQUEUED] sent=True` but no Telegram message received

**Check:**
1. Telegram logs - is there a `[TELEGRAM_SEND]` entry?
2. Telegram logs - is there a `[TELEGRAM_ERROR]` entry?
3. Check the error status code and body

### Issue: Alert shows `[ALERT_ENQUEUED] sent=False`

**Check:**
1. Telegram logs for error details
2. Check if Telegram is enabled (RUN_TELEGRAM env var)
3. Check if origin gatekeeper blocked the alert (should not happen for AWS origin)

## Script Usage

### Remote Debug Script

```bash
# Basic usage (30 minute window)
bash scripts/debug_alert_pipeline_remote.sh TON_USDT

# Custom time window (60 minutes)
bash scripts/debug_alert_pipeline_remote.sh TON_USDT 60

# Different symbol
bash scripts/debug_alert_pipeline_remote.sh BTC_USDT 15
```

### Local Monitoring API Script

```bash
# Check local backend monitoring API
bash scripts/debug_monitoring_api_local.sh
```

**Note:** This requires the local backend to be running on `http://localhost:8000`

## Example Output

```
===================================================================
ALERT PIPELINE DEBUG for TON_USDT (last 30m)
===================================================================

===================================================================
STRATEGY: DEBUG_STRATEGY_FINAL for TON_USDT (last 30m)
===================================================================
[DEBUG_STRATEGY_FINAL] symbol=TON_USDT | decision=BUY | buy_signal=True | sell_signal=False

===================================================================
SIGNAL MONITOR for TON_USDT (last 30m)
===================================================================
SignalMonitor: evaluating symbol=TON_USDT
[DEBUG_SIGNAL_MONITOR] symbol=TON_USDT side=BUY accepted=True

===================================================================
ALERT PIPELINE (ALERT_ logs) for TON_USDT (last 30m)
===================================================================
[ALERT_DECISION] symbol=TON_USDT side=BUY reason=RSI below threshold dry_run=False origin=AWS
[ALERT_ENQUEUED] symbol=TON_USDT side=BUY reason=RSI below threshold sent=True origin=AWS

===================================================================
TELEGRAM logs for TON_USDT (last 30m)
===================================================================
[TELEGRAM_SEND] symbol=TON_USDT side=BUY chat_id=123456789 origin=AWS
Telegram message sent successfully (origin=AWS)
```

## Additional Notes

- All timestamps in logs are in UTC
- The script uses `docker compose logs` which may have a slight delay
- For real-time debugging, you can tail logs directly:
  ```bash
  ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose logs -f backend-aws | grep TON_USDT'
  ```
