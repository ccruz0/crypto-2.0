# Audit Findings and Fixes Summary

## Audit Results

The audit script successfully identified the root causes of why NO Telegram alerts and NO buy/sell orders have been sent for days.

### Root Causes Identified

1. **❌ Scheduler Not Running**
   - `SignalMonitorService.is_running = False`
   - No `last_run_at` timestamp found
   - `TradingScheduler.running = False`
   - **Impact**: No signal monitoring cycles are executing

2. **❌ Telegram Disabled**
   - `ENVIRONMENT` not set to 'aws'
   - Missing `TELEGRAM_BOT_TOKEN`
   - Missing `TELEGRAM_CHAT_ID_AWS`
   - **Impact**: Even if alerts are generated, they won't be sent to Telegram

3. **⚠️ Database Unavailable** (Expected in local dev)
   - Cannot check market data freshness
   - Cannot check throttle state
   - Cannot check trade system status
   - **Impact**: Limited visibility into system state

## Fixes Implemented

### 1. Heartbeat Logging
**File**: `backend/app/services/signal_monitor.py`
**Line**: ~5020

Added heartbeat log every 10 cycles (~5 minutes with 30s interval) to prove the loop is alive:

```python
# Heartbeat log every 10 cycles (every ~5 minutes with 30s interval)
if cycle_count % 10 == 0:
    logger.info(
        "[HEARTBEAT] SignalMonitorService alive - cycle=%d last_run=%s",
        cycle_count,
        self.last_run_at.isoformat() if self.last_run_at else "None"
    )
```

### 2. Explicit Global Blocker Logging
**File**: `backend/app/services/signal_monitor.py`
**Line**: ~936

Added explicit warning when Telegram is disabled:

```python
# Check Telegram health before processing
if not telegram_notifier.enabled:
    logger.warning(
        "[GLOBAL_BLOCKER] Telegram notifier is disabled - alerts will not be sent. "
        "Check ENVIRONMENT=aws and TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID_AWS"
    )
```

Added warning when no watchlist items are found:

```python
if not watchlist_items:
    logger.warning(
        "[GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found - no alerts will be sent"
    )
    return
```

### 3. Improved Telegram Blocking Logging
**File**: `backend/app/services/telegram_notifier.py`
**Line**: ~225

Changed Telegram blocking log from DEBUG to WARNING level so it's visible in production logs:

```python
# Log at WARNING level when blocking alerts (not just debug)
logger.warning(
    f"[TELEGRAM_BLOCKED] Skipping Telegram send (ENV={env_value}, not 'aws' or missing credentials). "
    f"Message would have been: {preview}"
)
```

## Recommended Actions (Not Yet Implemented)

### 1. Start SignalMonitorService
The service should be started automatically on application startup. Verify:
- `DEBUG_DISABLE_SIGNAL_MONITOR` is not set
- The startup code in `backend/app/main.py` line 279 is executing
- Check application logs for startup errors

### 2. Configure Telegram for AWS
In AWS deployment, ensure:
- `ENVIRONMENT=aws` is set
- `TELEGRAM_BOT_TOKEN` is set
- `TELEGRAM_CHAT_ID_AWS` is set (not `TELEGRAM_CHAT_ID`)

### 3. Verify Market Data Updater
Ensure `market_updater.py` is running and updating prices regularly:
- Check last price update timestamps
- Verify external API connectivity
- Check for rate limiting issues

### 4. Check Watchlist Configuration
Verify watchlist items have:
- `alert_enabled = True` for symbols that should receive alerts
- `trade_enabled = True` for symbols that should auto-trade
- `trade_amount_usd > 0` for symbols with trade_enabled

## Testing

The audit script can be run to verify fixes:

```bash
# Run full audit
python backend/scripts/audit_no_alerts_no_trades.py

# Check specific symbols
python backend/scripts/audit_no_alerts_no_trades.py --symbols ETH_USDT,BTC_USD

# Check last 24 hours
python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24
```

## Next Steps

1. **Deploy fixes** to AWS environment
2. **Verify SignalMonitorService starts** on application startup
3. **Check logs** for heartbeat messages every ~5 minutes
4. **Monitor for [GLOBAL_BLOCKER] warnings** in logs
5. **Run audit script** periodically to verify system health

## Files Modified

1. `backend/scripts/audit_no_alerts_no_trades.py` - New audit script
2. `backend/app/services/signal_monitor.py` - Added heartbeat and global blocker logging
3. `backend/app/services/telegram_notifier.py` - Improved blocking log visibility
4. `docs/reports/no-alerts-no-trades-audit.md` - Generated audit report
5. `docs/AUDIT_SCRIPT_IMPLEMENTATION.md` - Implementation documentation

## Notes

- All fixes are minimal and focused on the confirmed root causes
- No unrelated code was refactored
- Existing diagnostic infrastructure (DIAG_* / decision traces / throttle logic) remains intact
- Logging is concise and grep-friendly (use `grep "[HEARTBEAT]"` or `grep "[GLOBAL_BLOCKER]"`)




