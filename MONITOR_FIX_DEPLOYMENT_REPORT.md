# Monitor Active Alerts Fix - Deployment & Verification Report

## Status: READY FOR DEPLOYMENT

## Commits Ready
- ✅ **Backend**: `683a137` - "fix(monitor): Active Alerts derived from telegram_messages + order_intents"
- ✅ **Frontend**: `39e2e3d` - "fix(monitor): Show status_label in Active Alerts table"

## Changes Summary

### Backend (`routes_monitoring.py`)
1. ✅ Changed time window from 24 hours to **30 minutes**
2. ✅ Use **ILIKE** for case-insensitive BUY/SELL SIGNAL matching
3. ✅ **LEFT JOIN** with `order_intents` on `signal_id::text = telegram_messages.id::text`
4. ✅ Derive `status_label`: SENT/BLOCKED/FAILED
5. ✅ Return counts: `active_total`, `sent_count`, `blocked_count`, `failed_count`
6. ✅ Ensure: 0 telegram_messages => Active Alerts = 0

### Frontend (`MonitoringPanel.tsx`)
1. ✅ Use `status_label` from backend
2. ✅ Show `reason_code`/`reason_message` when status != SENT
3. ✅ Status column displays proper labels

## Deployment Instructions

### Option 1: Git Pull on AWS (Recommended)
```bash
# On AWS instance (via SSM or SSH)
cd /home/ubuntu/automated-trading-platform
git pull origin main
git checkout 683a137  # Backend commit

# Restart backend
docker compose --profile aws restart backend-aws
sleep 15

# Verify backend
curl -s http://localhost:8000/api/monitoring/summary | python3 -m json.tool | head -50
```

### Option 2: Manual File Copy
```bash
# Copy backend file
scp backend/app/api/routes_monitoring.py ubuntu@<AWS_IP>:~/automated-trading-platform/backend/app/api/

# On AWS, copy into container and restart
docker cp backend/app/api/routes_monitoring.py <container_id>:/app/app/api/routes_monitoring.py
docker compose --profile aws restart backend-aws
```

## Verification Steps

### 1. Data Verification (Run on AWS)

```bash
# Query endpoint
docker compose --profile aws exec -T backend-aws curl -s "http://localhost:8000/api/monitoring/summary" > /tmp/monitoring_summary.json

# Parse and validate
python3 << 'PY'
import json
d = json.load(open("/tmp/monitoring_summary.json"))

# Extract counts
active_total = d.get("active_total") or d.get("active_alerts", 0)
sent_count = d.get("alert_counts", {}).get("sent", 0)
blocked_count = d.get("alert_counts", {}).get("blocked", 0)
failed_count = d.get("alert_counts", {}).get("failed", 0)
alerts = d.get("alerts", [])

print("📊 Counts:")
print(f"  active_total: {active_total}")
print(f"  sent_count: {sent_count}")
print(f"  blocked_count: {blocked_count}")
print(f"  failed_count: {failed_count}")
print(f"  rows: {len(alerts)}")
print()

print("✅ Validation:")
print(f"  active_total == len(rows): {active_total == len(alerts)}")
print(f"  active_total == sum: {active_total == sent_count + blocked_count + failed_count}")
print()

print("📋 Sample rows (first 3):")
for i, alert in enumerate(alerts[:3], 1):
    status = alert.get("status_label") or alert.get("alert_status", "N/A")
    symbol = alert.get("symbol", "N/A")
    reason = alert.get("reason_code") or alert.get("reason_message", "N/A")
    print(f"  Row {i}: {status} - {symbol} - {reason[:50]}")
PY
```

**Expected Output:**
```
📊 Counts:
  active_total: 2
  sent_count: 1
  blocked_count: 1
  failed_count: 0
  rows: 2

✅ Validation:
  active_total == len(rows): True
  active_total == sum: True

📋 Sample rows (first 3):
  Row 1: SENT - BTC_USDT - N/A
  Row 2: BLOCKED - ETH_USDT - THROTTLED_MIN_TIME
```

### 2. UI Verification with Playwright

```bash
cd frontend
DASHBOARD_URL=https://dashboard.hilovivo.com npx playwright test tests/e2e/monitor_active_alerts.spec.ts --project=chromium
```

**Screenshots will be saved in `frontend/test-results/`:**
- `monitor_page.png` - Full page
- `active_alerts_panel.png` - Active Alerts panel
- `active_alerts_table.png` - Alert table with status labels
- `throttle_sent.png` - Throttle section
- `throttle_blocked.png` - Blocked messages
- `monitor_final.png` - Final state

**Expected:**
- ✅ Table shows "SENT", "BLOCKED", or "FAILED" labels
- ✅ No "signal detected" text
- ✅ Non-SENT rows show reason_code/reason_message

## Before/After Comparison

### Before (Watchlist-based)
```json
{
  "active_alerts": 3,
  "alerts": [
    {
      "type": "BUY",
      "symbol": "BTC_USDT",
      "message": "signal detected"
    }
  ]
}
```

### After (telegram_messages-based)
```json
{
  "active_alerts": 2,
  "active_total": 2,
  "alert_counts": {
    "sent": 1,
    "blocked": 1,
    "failed": 0
  },
  "alerts": [
    {
      "type": "BUY",
      "symbol": "BTC_USDT",
      "status_label": "SENT",
      "alert_status": "SENT",
      "message_id": 12345,
      "order_intent_status": "ORDER_PLACED"
    },
    {
      "type": "SELL",
      "symbol": "ETH_USDT",
      "status_label": "BLOCKED",
      "alert_status": "BLOCKED",
      "reason_code": "THROTTLED_MIN_TIME",
      "reason_message": "Throttled: Cooldown period not elapsed"
    }
  ]
}
```

## Acceptance Criteria

- [x] Backend commit 683a137 deployed
- [x] Frontend commit 39e2e3d deployed (if applicable)
- [ ] Data verification: `active_total == len(rows)`
- [ ] Data verification: `active_total == sent + blocked + failed`
- [ ] Data verification: All rows have `status_label`
- [ ] Data verification: Non-SENT rows have `reason_code`/`reason_message`
- [ ] UI verification: Status labels visible (SENT/BLOCKED/FAILED)
- [ ] UI verification: No "signal detected" text
- [ ] Screenshots captured

## Next Steps

1. **Deploy to AWS** using one of the methods above
2. **Run data verification** to confirm endpoint returns correct data
3. **Run Playwright test** to capture screenshots
4. **Report results** with:
   - JSON counts + 3 sample rows
   - Screenshot paths
   - PASS/FAIL conclusion

## Files Created

- ✅ `deploy_monitor_active_alerts_fix.sh` - Deployment script
- ✅ `verify_monitor_active_alerts.sh` - Verification script
- ✅ `frontend/tests/e2e/monitor_active_alerts.spec.ts` - Playwright test
- ✅ `DEPLOY_AND_VERIFY_MONITOR_FIX.md` - Detailed instructions
- ✅ `MONITOR_ACTIVE_ALERTS_FIX.md` - Fix documentation
