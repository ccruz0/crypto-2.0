# Post-Deployment Checklist

## Immediate Checks (After Deployment Completes)

### 1. Verify Deployment Success

```bash
# Check deployment status
./check_deployment_status.sh

# Or manually check
aws ssm get-command-invocation \
  --command-id aa64b511-3d0f-4a9f-ae3b-e47efcaf1df5 \
  --instance-id i-08726dc37133b2454 \
  --region ap-southeast-1
```

### 2. Verify Container is Running

```bash
# SSH into AWS server
ssh your-aws-server

# Check container status
docker compose --profile aws ps

# Should show backend-aws container as "Up"
```

### 3. Check Heartbeat Logs

```bash
# On AWS server
docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT

# Should see messages like:
# [HEARTBEAT] SignalMonitorService alive - cycle=10 last_run=2026-01-01T...
```

**If no heartbeat:**
- Wait 5-10 minutes (heartbeat appears every ~5 minutes)
- Check if SignalMonitorService started: `docker logs automated-trading-platform-backend-aws-1 | grep "Signal monitor service"`
- Check for errors: `docker logs automated-trading-platform-backend-aws-1 | grep -i error | tail -20`

### 4. Check for Global Blockers

```bash
# On AWS server
docker logs automated-trading-platform-backend-aws-1 | grep GLOBAL_BLOCKER

# If you see warnings, they indicate critical issues:
# [GLOBAL_BLOCKER] Telegram notifier is disabled
# [GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found
```

### 5. View Audit Report

```bash
# On AWS server
ls -la docs/reports/no-alerts-no-trades-audit-*.md

# View latest report
cat docs/reports/no-alerts-no-trades-audit-*.md | tail -1 | xargs cat

# Or download to local machine
scp your-aws-server:/home/ubuntu/automated-trading-platform/docs/reports/no-alerts-no-trades-audit-*.md ./
```

## What to Look For in Audit Report

### GLOBAL STATUS Section
- **PASS** = All systems healthy
- **FAIL** = Critical issues found

### Root Causes Section
Ranked list of what's blocking alerts/trades:
1. Most common blocker (highest count)
2. Second most common
3. etc.

### Recommended Fixes Section
Specific actions with file/line references:
- Issue description
- Exact fix to apply
- File and line number

## Common Issues and Fixes

### Issue: Scheduler Not Running

**Symptoms:**
- Audit shows: `SignalMonitorService.is_running = False`
- No heartbeat logs

**Fix:**
```bash
# Check if disabled
docker exec automated-trading-platform-backend-aws-1 env | grep DEBUG_DISABLE_SIGNAL_MONITOR

# If not set, start manually via API
curl -X POST http://localhost:8002/api/control/start-signal-monitor

# Or restart container
docker compose --profile aws restart backend-aws
```

### Issue: Telegram Disabled

**Symptoms:**
- Audit shows: `Telegram notifier disabled`
- Logs show: `[TELEGRAM_BLOCKED]` or `[GLOBAL_BLOCKER] Telegram notifier is disabled`

**Fix:**
```bash
# Check environment variables
docker exec automated-trading-platform-backend-aws-1 env | grep -E "ENVIRONMENT|TELEGRAM"

# Edit .env.aws on AWS server
nano .env.aws

# Add/verify:
# ENVIRONMENT=aws
# TELEGRAM_BOT_TOKEN=your_token_here
# TELEGRAM_CHAT_ID_AWS=your_chat_id_here

# Restart to load new env vars
docker compose --profile aws restart backend-aws
```

### Issue: No Watchlist Items

**Symptoms:**
- Audit shows: `No watchlist items with alert_enabled=True found`
- Logs show: `[GLOBAL_BLOCKER] No watchlist items with alert_enabled=True found`

**Fix:**
- Enable alerts in dashboard for symbols that should receive alerts
- Set `alert_enabled = true` in database for relevant symbols

### Issue: Market Data Stale

**Symptoms:**
- Audit shows: `X symbols with stale prices (>30min old)`
- Per-symbol shows: `SKIP_MARKET_DATA_STALE`

**Fix:**
```bash
# Check market-updater is running
docker compose --profile aws ps market-updater-aws

# If not running, start it
docker compose --profile aws up -d market-updater-aws

# Check logs
docker logs market-updater-aws --tail 100
```

## Verification Steps

After applying fixes:

1. **Re-run Audit**
   ```bash
   # On AWS server
   docker exec automated-trading-platform-backend-aws-1 \
     python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24
   ```

2. **Check Heartbeat**
   ```bash
   docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT | tail -5
   ```

3. **Check No Blockers**
   ```bash
   docker logs automated-trading-platform-backend-aws-1 | grep GLOBAL_BLOCKER
   # Should return nothing (or only expected warnings)
   ```

4. **Test Alert Flow**
   - Wait for a signal to be detected
   - Check Telegram channel for alert
   - Verify alert was sent

## Monitoring Setup

### Set Up Alerts

1. **Heartbeat Monitoring**
   - Alert if no heartbeat for 10+ minutes
   - Pattern: `[HEARTBEAT] SignalMonitorService alive`
   - Use CloudWatch Logs Insights or similar

2. **Global Blocker Alerts**
   - Alert immediately on any `[GLOBAL_BLOCKER]` warning
   - These indicate critical issues

3. **Daily Audit**
   - Schedule daily audit runs
   - Email/Slack notification if status is FAIL

### Log Monitoring Queries

```bash
# Heartbeat check (should appear every ~5 minutes)
grep "[HEARTBEAT]" logs/app.log

# Global blockers (should be empty)
grep "[GLOBAL_BLOCKER]" logs/app.log

# Telegram blocking (check if expected)
grep "[TELEGRAM_BLOCKED]" logs/app.log
```

## Success Criteria

You'll know everything is working when:

✅ Heartbeat logs appear every ~5 minutes  
✅ No [GLOBAL_BLOCKER] warnings  
✅ Audit report shows GLOBAL STATUS: PASS  
✅ SignalMonitorService is running  
✅ Telegram alerts are being sent (if configured)  
✅ Buy/sell orders are being placed (if trade_enabled)  

## Next Actions

1. ✅ Wait for deployment to complete
2. ⏳ Check deployment status
3. ⏳ Review audit report
4. ⏳ Fix issues identified in audit
5. ⏳ Re-run audit to verify fixes
6. ⏳ Set up monitoring/alerts




