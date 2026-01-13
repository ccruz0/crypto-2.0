# Deploy and Verify Monitor Active Alerts Fix

## Summary
This document provides instructions for deploying and verifying the Monitor Active Alerts fix that derives alerts from `telegram_messages` + `order_intents` instead of Watchlist signal detection.

## Commits
- **Backend**: `683a137` - "fix(monitor): Active Alerts derived from telegram_messages + order_intents"
- **Frontend**: `39e2e3d` - "fix(monitor): Show status_label in Active Alerts table"

## Deployment

### Option 1: Using SSM Script (Recommended)
```bash
./deploy_monitor_active_alerts_fix.sh
```

### Option 2: Manual Deployment via SSM
```bash
# 1. Verify commits exist locally
git rev-parse --verify 683a137
git -C frontend rev-parse --verify 39e2e3d

# 2. Deploy backend file
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name "AWS-RunShellScript" \
  --parameters commands="[
    'cd /home/ubuntu/automated-trading-platform',
    'git pull origin main',
    'git checkout 683a137',
    'docker compose --profile aws restart backend-aws',
    'sleep 15'
  ]" \
  --region ap-southeast-1

# 3. Deploy frontend (if needed)
cd frontend
git checkout 39e2e3d
# Rebuild frontend container
```

## Verification

### Step 1: Data Verification

Run the verification script:
```bash
./verify_monitor_active_alerts.sh
```

Or manually via SSM:
```bash
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name "AWS-RunShellScript" \
  --parameters commands="[
    'cd /home/ubuntu/automated-trading-platform',
    'docker compose --profile aws exec -T backend-aws curl -s http://localhost:8000/api/monitoring/summary > /tmp/monitoring_summary.json',
    'python3 -c \"import json; d=json.load(open(\\\"/tmp/monitoring_summary.json\\\")); print(\\\"active_total:\\\", d.get(\\\"active_total\\\", d.get(\\\"active_alerts\\\", 0))); print(\\\"sent:\\\", d.get(\\\"alert_counts\\\", {}).get(\\\"sent\\\", 0)); print(\\\"blocked:\\\", d.get(\\\"alert_counts\\\", {}).get(\\\"blocked\\\", 0)); print(\\\"failed:\\\", d.get(\\\"alert_counts\\\", {}).get(\\\"failed\\\", 0)); alerts=d.get(\\\"alerts\\\", []); print(\\\"rows:\\\", len(alerts)); [print(f\\\"Row {i}: {a.get(\\\"status_label\\\", a.get(\\\"alert_status\\\", \\\"N/A\\\"))} - {a.get(\\\"symbol\\\", \\\"N/A\\\")}\\\") for i, a in enumerate(alerts[:3], 1)]\"'
  ]" \
  --region ap-southeast-1
```

**Acceptance Criteria:**
- ✅ `active_total == len(rows)`
- ✅ `active_total == sent_count + blocked_count + failed_count`
- ✅ Each row includes `status_label` (SENT/BLOCKED/FAILED)
- ✅ If `status_label != SENT`, `reason_code`/`reason_message` present

### Step 2: UI Verification with Playwright

```bash
cd frontend
npx playwright test tests/e2e/monitor_active_alerts.spec.ts --project=chromium
```

Screenshots will be saved in `frontend/test-results/`:
- `monitor_page.png` - Full page
- `active_alerts_panel.png` - Active Alerts panel
- `active_alerts_table.png` - Alert table
- `throttle_sent.png` - Throttle section
- `throttle_blocked.png` - Blocked messages section
- `monitor_final.png` - Final state

**Acceptance Criteria:**
- ✅ Table contains at least one "SENT/BLOCKED/FAILED" label
- ✅ No "signal detected" text found
- ✅ Status labels are visible in the table

## Expected JSON Response

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
      "timestamp": "2025-01-27T12:05:00Z",
      "message_id": 12345,
      "order_intent_status": "ORDER_PLACED"
    },
    {
      "type": "SELL",
      "symbol": "ETH_USDT",
      "status_label": "BLOCKED",
      "alert_status": "BLOCKED",
      "reason_code": "THROTTLED_MIN_TIME",
      "reason_message": "Throttled: Cooldown period not elapsed",
      "timestamp": "2025-01-27T12:03:00Z"
    }
  ]
}
```

## Troubleshooting

### Issue: Empty response from endpoint
- Check backend container is running: `docker compose --profile aws ps`
- Check backend logs: `docker compose --profile aws logs backend-aws`
- Verify endpoint: `curl http://localhost:8000/api/monitoring/summary`

### Issue: No status labels in UI
- Clear browser cache
- Check frontend container is running
- Verify frontend commit is deployed: `git -C frontend log -1 --oneline`

### Issue: active_total != sum of counts
- Check for errors in backend logs
- Verify telegram_messages table has data in last 30 minutes
- Check order_intents table exists and has data

## Report Template

```
## Deployment Status
- Backend commit: [683a137 / other]
- Frontend commit: [39e2e3d / other]
- Deployment time: [timestamp]

## Data Verification
- active_total: [number]
- sent_count: [number]
- blocked_count: [number]
- failed_count: [number]
- rows: [number]
- Validation: [PASS/FAIL with details]

## Sample Rows
[First 3 rows with status_label, symbol, reason_code]

## UI Verification
- Screenshots: [paths]
- Status labels found: [yes/no]
- "signal detected" found: [yes/no]
- Conclusion: [PASS/FAIL]
```
