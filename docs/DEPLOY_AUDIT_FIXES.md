# Deploy Audit Fixes - Quick Guide

## Quick Deploy

```bash
# Make scripts executable
chmod +x deploy_audit_fixes.sh run_audit_in_production.sh

# Deploy fixes
./deploy_audit_fixes.sh

# Run audit in production
./run_audit_in_production.sh
```

## Manual Deployment

### 1. Deploy Backend with Fixes

```bash
cd /path/to/automated-trading-platform

# Build and start
docker compose --profile aws build backend-aws
docker compose --profile aws up -d backend-aws

# Restart to ensure env vars load
docker compose --profile aws restart backend-aws
```

### 2. Verify Deployment

```bash
# Check heartbeat (should appear every ~5 minutes)
docker logs -f backend-aws | grep HEARTBEAT

# Check for global blockers
docker logs backend-aws | grep GLOBAL_BLOCKER

# Verify SignalMonitorService started
docker logs backend-aws | grep "Signal monitor service"
```

### 3. Run Audit

```bash
# Full audit (last 7 days)
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 168

# Specific symbols
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py \
  --symbols ETH_USDT,BTC_USD --since-hours 24

# Last 24 hours
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24
```

## What to Look For

### After Deployment

1. **Heartbeat Messages** (every ~5 minutes):
   ```
   [HEARTBEAT] SignalMonitorService alive - cycle=10 last_run=2026-01-01T12:00:00+00:00
   ```

2. **Global Blocker Warnings** (if issues exist):
   ```
   [GLOBAL_BLOCKER] Telegram notifier is disabled - alerts will not be sent
   [GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found
   ```

3. **Telegram Blocking** (if disabled):
   ```
   [TELEGRAM_BLOCKED] Skipping Telegram send (ENV=local, not 'aws')
   ```

### In Audit Report

Check the generated report at `docs/reports/no-alerts-no-trades-audit.md`:

1. **GLOBAL STATUS**: Should be PASS if everything is working
2. **Root Causes**: Ranked list of what's blocking alerts/trades
3. **Recommended Fixes**: Specific actions to take

## Common Issues and Fixes

### Issue: No Heartbeat Messages

**Check:**
```bash
# Is SignalMonitorService running?
docker logs backend-aws | grep "Signal monitor service"

# Check for startup errors
docker logs backend-aws | grep "Failed to start signal monitor"

# Check if disabled
docker exec backend-aws env | grep DEBUG_DISABLE_SIGNAL_MONITOR
```

**Fix:**
- Ensure `DEBUG_DISABLE_SIGNAL_MONITOR` is not set
- Check application startup logs for errors
- Manually start via API: `POST /api/control/start-signal-monitor`

### Issue: Telegram Disabled

**Check:**
```bash
docker exec backend-aws env | grep -E "ENVIRONMENT|TELEGRAM"
```

**Fix:**
- Set `ENVIRONMENT=aws` in `.env.aws`
- Set `TELEGRAM_BOT_TOKEN` in `.env.aws`
- Set `TELEGRAM_CHAT_ID_AWS` in `.env.aws`
- Restart: `docker compose --profile aws restart backend-aws`

### Issue: No Watchlist Items

**Check:**
```sql
-- Connect to database and check
SELECT symbol, alert_enabled, trade_enabled 
FROM watchlist_items 
WHERE is_deleted = false;
```

**Fix:**
- Enable alerts in dashboard for symbols that should receive alerts
- Set `alert_enabled = true` for symbols you want to monitor

## Monitoring Setup

### Set Up Log Monitoring

```bash
# Monitor heartbeat (alert if no heartbeat for 10+ minutes)
# Use CloudWatch Logs Insights or similar:
# Filter: [HEARTBEAT]
# Alert: No matches in last 10 minutes

# Monitor global blockers (alert immediately)
# Filter: [GLOBAL_BLOCKER]
# Alert: Any matches
```

### Schedule Daily Audits

Add to crontab or scheduled task:

```bash
# Run audit daily at 2 AM
0 2 * * * cd /path/to/repo && docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24 --output docs/reports/daily-audit-$(date +\%Y\%m\%d).md
```

## Verification Checklist

After deployment, verify:

- [ ] Backend container is running
- [ ] Heartbeat logs appear every ~5 minutes
- [ ] No [GLOBAL_BLOCKER] warnings (unless expected)
- [ ] SignalMonitorService started successfully
- [ ] Audit script runs without errors
- [ ] Audit report is generated
- [ ] Telegram is enabled (if alerts should be sent)
- [ ] Watchlist items have correct settings

## Troubleshooting

### Audit Script Fails

```bash
# Check Python dependencies
docker exec backend-aws python -c "import app.models.watchlist; print('OK')"

# Check database connection
docker exec backend-aws python -c "from app.database import SessionLocal; db = SessionLocal(); db.close(); print('OK')"

# Run with verbose output
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 1 -v
```

### Container Issues

```bash
# Check container status
docker compose --profile aws ps

# View logs
docker logs backend-aws --tail 100

# Restart if needed
docker compose --profile aws restart backend-aws
```

## Next Steps

1. ✅ Deploy fixes
2. ✅ Verify heartbeat is working
3. ✅ Run audit to identify blockers
4. ✅ Fix issues found in audit
5. ✅ Re-run audit to verify fixes
6. ✅ Set up monitoring/alerts
7. ✅ Schedule regular audits




