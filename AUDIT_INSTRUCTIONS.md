# How to Run the Audit - Instructions

## Quick Method (SSH into AWS)

```bash
# 1. SSH into your AWS server
ssh ubuntu@175.41.189.249
# (or use your configured SSH method)

# 2. Navigate to project directory
cd /home/ubuntu/automated-trading-platform

# 3. Find container name
docker compose --profile aws ps

# 4. Run audit
docker exec automated-trading-platform-backend-aws-1 \
  python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24

# 5. View full report
docker exec automated-trading-platform-backend-aws-1 \
  cat docs/reports/no-alerts-no-trades-audit.md

# 6. Check heartbeat (should appear every ~5 minutes)
docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT | tail -5

# 7. Check global blockers
docker logs automated-trading-platform-backend-aws-1 | grep GLOBAL_BLOCKER | tail -5
```

## What the Audit Will Show (Given You Have Active Alerts)

### Expected Results

Since you now have **6 active alerts** detected, the audit should show:

#### 1. GLOBAL STATUS
- **Likely: PASS** (or mostly PASS)
  - Scheduler: Should show as running (if cycles > 0)
  - Telegram: May show FAIL if alerts detected but not sent to Telegram
  - Market Data: Should show fresh data
  - Throttle: Should show recent activity
  - Trade System: Should show 18 open orders

#### 2. Per-Symbol Analysis
For symbols with alerts (ALGO_USDT, LINK_USDT, LDO_USD, TON_USDT, BTC_USD, DOT_USDT):

**If alerts are being sent to Telegram:**
- `alert_decision: EXEC`
- `alert_reason: EXEC_ALERT_SENT`
- `alert_blocked_by: None`

**If alerts are detected but NOT sent to Telegram:**
- `alert_decision: SKIP`
- `alert_reason: SKIP_TELEGRAM_DISABLED` or `SKIP_TELEGRAM_ERROR`
- `alert_blocked_by: TELEGRAM_DISABLED` or `TELEGRAM_ERROR`

#### 3. Root Causes
Should show:
- **Fewer blockers** than before
- May still show `SKIP_TELEGRAM_DISABLED` if Telegram not configured
- May show `SKIP_COOLDOWN_ACTIVE` if throttled
- Should NOT show `SKIP_NO_SIGNAL` for symbols with alerts

#### 4. Key Questions Answered

1. **Are alerts being sent to Telegram?**
   - Check if `alert_reason` shows `EXEC_ALERT_SENT` or `SKIP_TELEGRAM_*`
   - Check Telegram channel to verify

2. **Why scheduler cycles show 0?**
   - Audit will show if scheduler is actually running
   - May be display issue vs. actual problem

3. **What was blocking before?**
   - Compare audit results to understand what changed
   - Likely scheduler wasn't running or was blocked

## What Changed?

### Before Deployment
- ❌ No alerts detected
- ❌ System silent
- ❌ Likely scheduler not running or blocked

### After Deployment
- ✅ 6 active alerts detected
- ✅ Signals being generated
- ✅ System operational
- ⚠️ Need to verify Telegram delivery
- ⚠️ Need to verify scheduler cycles

## Key Metrics to Check

### 1. Telegram Status
```bash
# Check if Telegram is enabled
docker exec automated-trading-platform-backend-aws-1 env | grep -E "ENVIRONMENT|TELEGRAM"

# Should show:
# ENVIRONMENT=aws
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID_AWS=...
```

### 2. Scheduler Status
```bash
# Check scheduler logs
docker logs automated-trading-platform-backend-aws-1 | grep "Signal monitor service"

# Check heartbeat
docker logs automated-trading-platform-backend-aws-1 | grep HEARTBEAT | tail -5
```

### 3. Alert Delivery
- Check your Telegram channel
- Verify if the 6 alerts shown in dashboard actually appeared in Telegram
- If not, Telegram is likely disabled or misconfigured

## Expected Audit Output

```
GLOBAL STATUS: PASS (or mostly PASS)

Global Health Checks:
- SCHEDULER: PASS (if cycles > 0) or FAIL (if cycles = 0)
- TELEGRAM: PASS (if alerts sent) or FAIL (if disabled)
- MARKET_DATA: PASS (fresh data)
- THROTTLE: PASS (recent activity)
- TRADE_SYSTEM: PASS (18 open orders)

Per-Symbol Analysis:
- ALGO_USDT: alert_decision=EXEC, alert_reason=EXEC_ALERT_SENT (if Telegram working)
- LINK_USDT: alert_decision=EXEC, alert_reason=EXEC_ALERT_SENT
- ... (other symbols with alerts)

Root Causes:
- SKIP_TELEGRAM_DISABLED: X occurrences (if Telegram not configured)
- SKIP_COOLDOWN_ACTIVE: Y occurrences (if throttled)
```

## Next Steps After Audit

1. **If Telegram is disabled:**
   - Set `ENVIRONMENT=aws` in `.env.aws`
   - Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID_AWS`
   - Restart: `docker compose --profile aws restart backend-aws`

2. **If scheduler cycles = 0:**
   - Check if SignalMonitorService is running
   - Check logs for errors
   - May need to start manually via API

3. **If alerts are being sent:**
   - ✅ Everything is working!
   - Monitor heartbeat to ensure continued operation
   - Set up alerts for global blockers

## Summary

You have **6 active alerts** which is great progress! The audit will tell you:
- ✅ What's working (signals detected)
- ⚠️ What needs fixing (Telegram delivery, scheduler cycles)
- 📊 Detailed per-symbol analysis
- 🔍 Root causes of any remaining blockers

Run the audit to get the complete picture!





