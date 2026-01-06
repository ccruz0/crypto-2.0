# Audit Implementation - Action Plan

## ✅ What's Been Completed

1. **Audit Script** (`backend/scripts/audit_no_alerts_no_trades.py`)
   - Comprehensive end-to-end audit
   - Global health checks + per-symbol analysis
   - Generates markdown reports with root causes

2. **Minimal Fixes**
   - Heartbeat logging (every 10 cycles)
   - Global blocker warnings
   - Improved Telegram blocking visibility

3. **Regression Tests** (`backend/tests/test_audit_reason_codes.py`)
   - 10 tests covering all scenarios
   - All tests passing ✅

4. **Deployment Scripts**
   - `deploy_audit_fixes.sh` - Deploy fixes to AWS
   - `run_audit_in_production.sh` - Run audit in production

## 🚀 Next Steps (In Order)

### Step 1: Deploy Fixes to AWS

```bash
# Quick deploy
./deploy_audit_fixes.sh

# Or manually
docker compose --profile aws build backend-aws
docker compose --profile aws up -d backend-aws
docker compose --profile aws restart backend-aws
```

**Verify:**
```bash
# Check heartbeat (should appear every ~5 minutes)
docker logs -f backend-aws | grep HEARTBEAT

# Check for global blockers
docker logs backend-aws | grep GLOBAL_BLOCKER
```

### Step 2: Run Audit in Production

```bash
# Quick audit
./run_audit_in_production.sh

# Or manually
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py --since-hours 168
```

**Review the report:**
- Open `docs/reports/no-alerts-no-trades-audit.md`
- Check GLOBAL STATUS (PASS/FAIL)
- Review root causes section
- Check recommended fixes

### Step 3: Fix Production Issues

Based on audit results, fix the actual blockers:

#### If Scheduler Not Running:
```bash
# Check startup logs
docker logs backend-aws | grep "Signal monitor service"

# Check if disabled
docker exec backend-aws env | grep DEBUG_DISABLE_SIGNAL_MONITOR

# Start manually via API (if needed)
curl -X POST http://your-api/api/control/start-signal-monitor
```

#### If Telegram Disabled:
```bash
# Check environment
docker exec backend-aws env | grep -E "ENVIRONMENT|TELEGRAM"

# Fix in .env.aws:
# ENVIRONMENT=aws
# TELEGRAM_BOT_TOKEN=your_token
# TELEGRAM_CHAT_ID_AWS=your_chat_id

# Restart
docker compose --profile aws restart backend-aws
```

#### If Market Data Stale:
```bash
# Check market-updater logs
docker logs market-updater-aws --tail 100

# Verify it's running
docker compose --profile aws ps market-updater-aws
```

### Step 4: Verify Fixes

```bash
# Re-run audit
./run_audit_in_production.sh 24

# Check heartbeat is working
docker logs backend-aws | grep HEARTBEAT | tail -5

# Check no global blockers
docker logs backend-aws | grep GLOBAL_BLOCKER
```

### Step 5: Set Up Monitoring

```bash
# Monitor heartbeat (alert if missing for 10+ minutes)
# Use CloudWatch or your monitoring system

# Monitor global blockers (alert immediately)
# Filter: [GLOBAL_BLOCKER]
```

## 📋 Quick Reference

### Run Audit
```bash
# Full audit (7 days)
./run_audit_in_production.sh

# Last 24 hours
./run_audit_in_production.sh 24

# Specific symbols
docker exec backend-aws python backend/scripts/audit_no_alerts_no_trades.py \
  --symbols ETH_USDT,BTC_USD --since-hours 24
```

### Check Logs
```bash
# Heartbeat (proves loop is alive)
docker logs backend-aws | grep HEARTBEAT

# Global blockers (critical issues)
docker logs backend-aws | grep GLOBAL_BLOCKER

# Telegram blocking
docker logs backend-aws | grep TELEGRAM_BLOCKED
```

### Common Commands
```bash
# Deploy fixes
./deploy_audit_fixes.sh

# Run audit
./run_audit_in_production.sh

# Check container status
docker compose --profile aws ps

# View logs
docker logs backend-aws --tail 100 -f

# Restart service
docker compose --profile aws restart backend-aws
```

## 📚 Documentation

- `docs/AUDIT_SCRIPT_IMPLEMENTATION.md` - How the audit script works
- `docs/AUDIT_FINDINGS_AND_FIXES.md` - What was found and fixed
- `docs/AUDIT_COMPLETE_SUMMARY.md` - Complete implementation summary
- `docs/DEPLOY_AUDIT_FIXES.md` - Deployment guide
- `docs/NEXT_STEPS_AUDIT.md` - Detailed next steps
- `AUDIT_ACTION_PLAN.md` - This file

## 🎯 Success Criteria

You'll know everything is working when:

1. ✅ Heartbeat logs appear every ~5 minutes
2. ✅ No [GLOBAL_BLOCKER] warnings in logs
3. ✅ Audit report shows GLOBAL STATUS: PASS
4. ✅ Telegram alerts are being sent (if configured)
5. ✅ Buy/sell orders are being placed (if trade_enabled)

## 🆘 Troubleshooting

### No Heartbeat
- Check SignalMonitorService started
- Check DEBUG_DISABLE_SIGNAL_MONITOR is not set
- Check startup logs for errors

### Audit Fails
- Check database connectivity
- Verify Python dependencies
- Check container is running

### Still No Alerts
- Run audit to identify blockers
- Check Telegram configuration
- Verify watchlist settings
- Check throttle state

## 📞 Support

If you need help:
1. Run audit: `./run_audit_in_production.sh`
2. Review report: `docs/reports/no-alerts-no-trades-audit.md`
3. Check logs for [HEARTBEAT], [GLOBAL_BLOCKER], [TELEGRAM_BLOCKED]
4. Review documentation in `docs/` directory




