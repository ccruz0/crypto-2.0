# Next Steps - Audit Implementation

## Immediate Actions

### 1. Deploy Changes to AWS
Deploy the fixes to your AWS environment:

```bash
# Build and deploy backend with new fixes
cd /Users/carloscruz/automated-trading-platform
docker-compose build backend
docker-compose up -d backend

# Or if using AWS deployment scripts
./deploy.sh  # or your deployment command
```

**What to verify after deployment:**
- Check logs for `[HEARTBEAT]` messages (should appear every ~5 minutes)
- Check for `[GLOBAL_BLOCKER]` warnings
- Verify SignalMonitorService starts on application startup

### 2. Run Audit Script in Production
Once deployed, run the audit script against your production database:

```bash
# SSH into AWS instance or run in container
python backend/scripts/audit_no_alerts_no_trades.py --since-hours 168

# Or run for specific symbols you're concerned about
python backend/scripts/audit_no_alerts_no_trades.py --symbols ETH_USDT,BTC_USD --since-hours 24
```

**What to look for:**
- Review the generated report at `docs/reports/no-alerts-no-trades-audit.md`
- Check which root causes are actually blocking alerts/trades
- Verify if scheduler is running in production
- Check if Telegram is properly configured

### 3. Fix Production Issues Based on Audit
Based on the audit results, fix the actual blockers:

#### If Scheduler Not Running:
```bash
# Check if SignalMonitorService is starting
# Look in application logs for:
# - "Signal monitor service start() scheduled"
# - "[HEARTBEAT] SignalMonitorService alive"

# If not starting, check:
# - DEBUG_DISABLE_SIGNAL_MONITOR environment variable (should be unset)
# - Application startup logs for errors
# - Use API endpoint to start manually: POST /api/control/start-signal-monitor
```

#### If Telegram Disabled:
```bash
# Verify environment variables in AWS:
# - ENVIRONMENT=aws (required)
# - TELEGRAM_BOT_TOKEN=<your_token>
# - TELEGRAM_CHAT_ID_AWS=<your_chat_id>

# Check logs for:
# - "[TELEGRAM_BLOCKED]" warnings
# - "[GLOBAL_BLOCKER] Telegram notifier is disabled"
```

#### If Market Data Stale:
```bash
# Check if market_updater.py is running
# Verify last price update timestamps in database
# Check for API rate limiting or connectivity issues
```

### 4. Set Up Monitoring
Create alerts based on audit findings:

#### Monitor Heartbeat
```bash
# Set up log monitoring to alert if no heartbeat for 10+ minutes
# Example: CloudWatch alarm or log-based alert
# Pattern: "[HEARTBEAT] SignalMonitorService alive"
# Alert if: No matches in last 10 minutes
```

#### Monitor Global Blockers
```bash
# Alert on any [GLOBAL_BLOCKER] warnings
# These indicate critical issues preventing alerts/trades
```

#### Schedule Regular Audits
```bash
# Add cron job to run audit script daily
# 0 2 * * * cd /path/to/repo && python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24
# Send report to monitoring email/channel
```

### 5. Verify Watchlist Configuration
Check your watchlist items have correct settings:

```sql
-- Check watchlist items that should have alerts
SELECT symbol, alert_enabled, trade_enabled, trade_amount_usd, 
       buy_alert_enabled, sell_alert_enabled
FROM watchlist_items
WHERE is_deleted = false
ORDER BY symbol;

-- Symbols with alerts disabled but should have them
SELECT symbol, alert_enabled, trade_enabled
FROM watchlist_items
WHERE is_deleted = false
  AND (alert_enabled = false OR trade_enabled = false)
  AND symbol IN ('ETH_USDT', 'BTC_USD', ...);  -- Your important symbols
```

### 6. Test Alert Flow End-to-End
Once fixes are deployed, test the complete flow:

```bash
# 1. Verify SignalMonitorService is running
curl http://your-api/api/control/status | jq .signal_monitor_running

# 2. Check logs for heartbeat
tail -f logs/app.log | grep HEARTBEAT

# 3. Enable alerts for a test symbol
# (via dashboard or API)

# 4. Wait for signal and verify alert is sent
# Check Telegram channel for alert

# 5. Run audit to verify no blockers
python backend/scripts/audit_no_alerts_no_trades.py --symbols TEST_SYMBOL
```

## Long-term Improvements

### 1. Automated Health Checks
Consider adding automated health check endpoint:

```python
# GET /api/health/audit
# Returns quick health status based on audit checks
# Can be used by monitoring systems
```

### 2. Dashboard Integration
Add audit results to dashboard:
- Show global status (PASS/FAIL)
- Display top root causes
- Link to full audit report

### 3. Alert on Audit Failures
Set up automated alerts when audit shows FAIL status:
- Email/Slack notification
- Include audit report in notification
- Link to recommended fixes

### 4. Historical Tracking
Track audit results over time:
- Store audit results in database
- Graph trends (e.g., % symbols blocked over time)
- Identify recurring issues

## Verification Checklist

After deployment, verify:

- [ ] SignalMonitorService starts automatically on application startup
- [ ] Heartbeat logs appear every ~5 minutes in logs
- [ ] No [GLOBAL_BLOCKER] warnings in logs (unless expected)
- [ ] Telegram is enabled (ENVIRONMENT=aws, credentials set)
- [ ] Audit script runs successfully in production
- [ ] Audit report shows actionable root causes
- [ ] Watchlist items have correct alert_enabled/trade_enabled settings
- [ ] Market data is being updated regularly
- [ ] Test alert can be sent successfully

## Troubleshooting

### If Heartbeat Not Appearing
1. Check if SignalMonitorService started: `grep "Signal monitor service" logs/app.log`
2. Check for startup errors: `grep "Failed to start signal monitor" logs/app.log`
3. Verify DEBUG_DISABLE_SIGNAL_MONITOR is not set
4. Manually start via API: `POST /api/control/start-signal-monitor`

### If Audit Script Fails
1. Check database connectivity
2. Verify all required models are available
3. Check Python dependencies are installed
4. Run with `--mode dry` first to test

### If Alerts Still Not Sending
1. Run audit script to identify blockers
2. Check Telegram configuration (ENVIRONMENT, tokens)
3. Verify watchlist items have alert_enabled=True
4. Check throttle state (may be blocking due to recent alerts)
5. Verify market data is fresh (<30 minutes old)

## Support

If issues persist:
1. Run full audit: `python backend/scripts/audit_no_alerts_no_trades.py`
2. Review generated report: `docs/reports/no-alerts-no-trades-audit.md`
3. Check logs for [HEARTBEAT], [GLOBAL_BLOCKER], [TELEGRAM_BLOCKED]
4. Verify environment variables in AWS
5. Check SignalMonitorService status via API





