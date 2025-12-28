# Deployment Guide: ActiveAlerts Refactor

## Summary
This deployment updates the ActiveAlerts logic to be state-based from Watchlist toggles instead of event-based from SignalThrottleState.

## Changes Deployed
- **Commit**: `8d1a9e4` - "refactor: Make ActiveAlerts state-based from Watchlist toggles"
- **File**: `backend/app/api/routes_monitoring.py`
- **Status**: ✅ Committed and pushed to `origin/main`

## Deployment Steps

### Option 1: Manual SSH Deployment (Recommended)

1. **SSH into the AWS server:**
   ```bash
   ssh ubuntu@<server-ip>
   # Or use AWS Session Manager
   aws ssm start-session --target i-08726dc37133b2454 --region ap-southeast-1
   ```

2. **Navigate to project directory:**
   ```bash
   cd /home/ubuntu/automated-trading-platform
   ```

3. **Fix git ownership (if needed):**
   ```bash
   git config --global --add safe.directory /home/ubuntu/automated-trading-platform
   ```

4. **Pull latest changes:**
   ```bash
   git fetch origin
   git pull origin main
   ```

5. **Verify the changes are present:**
   ```bash
   git log --oneline -1
   # Should show: 8d1a9e4 refactor: Make ActiveAlerts state-based from Watchlist toggles
   
   grep -n "REFACTORED: ActiveAlerts" backend/app/api/routes_monitoring.py
   # Should show the new comment block
   ```

6. **Restart backend service:**
   ```bash
   docker compose --profile aws restart backend
   # Or if using different service name:
   docker compose --profile aws restart backend-aws
   ```

7. **Wait for backend to be ready:**
   ```bash
   sleep 20
   docker compose --profile aws ps
   ```

8. **Verify backend health:**
   ```bash
   curl http://localhost:8000/api/health
   ```

### Option 2: Using AWS SSM (Automated)

Run this command from your local machine:

```bash
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "git config --global --add safe.directory /home/ubuntu/automated-trading-platform",
    "git fetch origin",
    "git pull origin main",
    "docker compose --profile aws restart backend",
    "sleep 25",
    "docker compose --profile aws ps backend",
    "curl -s http://localhost:8000/api/health"
  ]' \
  --region ap-southeast-1
```

Then check the result:
```bash
# Get the command ID from the output above, then:
aws ssm get-command-invocation \
  --command-id <COMMAND_ID> \
  --instance-id i-08726dc37133b2454 \
  --region ap-southeast-1
```

## Verification Steps

### 1. Check ActiveAlerts Endpoint

```bash
curl -s http://localhost:8000/api/monitoring/summary | python3 -m json.tool | grep -A 2 "active_alerts"
```

Expected output should show:
- `"active_alerts": <number>` - This should match the sum of all enabled toggles in Watchlist

### 2. Verify in Dashboard

1. Open the Monitoring tab in the dashboard
2. Check the "Active Alerts" card at the top
3. The count should match the number of green/red buttons enabled in the Watchlist
4. Toggle an alert on/off in the Watchlist
5. Wait ~20 seconds (refresh interval)
6. Verify the alert appears/disappears in the ActiveAlerts panel

### 3. Test Behavior

- **Toggle ON**: Enable a BUY or SELL alert in Watchlist → Should appear in ActiveAlerts
- **Toggle OFF**: Disable an alert → Should disappear from ActiveAlerts
- **Remove Symbol**: Remove symbol from Watchlist → All its alerts should disappear
- **Page Refresh**: Refresh the page → Should NOT show old/historical alerts

## Expected Behavior

✅ **Active Alerts count** = Sum of all enabled toggles (green + red buttons)  
✅ **No historical alerts** - Only currently active toggles shown  
✅ **No throttled/blocked messages** - Only active state shown  
✅ **Real-time updates** - Changes reflect within ~20 seconds (refresh interval)  
✅ **Consistency** - Watchlist buttons match Monitoring tab

## Troubleshooting

### Backend not restarting
```bash
# Check container status
docker compose --profile aws ps

# Check logs
docker compose --profile aws logs backend --tail 50

# Force restart
docker compose --profile aws down backend
docker compose --profile aws up -d backend
```

### Git pull fails
```bash
# Fix ownership
git config --global --add safe.directory /home/ubuntu/automated-trading-platform

# Or reset and pull
git fetch origin
git reset --hard origin/main
```

### Endpoint not responding
```bash
# Check if backend is running
docker compose --profile aws ps backend

# Check backend logs
docker compose --profile aws logs backend --tail 100

# Test health endpoint
curl http://localhost:8000/api/health
```

## Rollback (if needed)

If you need to rollback:

```bash
cd /home/ubuntu/automated-trading-platform
git log --oneline -5  # Find previous commit
git reset --hard <previous-commit-hash>
docker compose --profile aws restart backend
```

## Deployment Status

- [x] Code committed to `main` branch
- [x] Code pushed to `origin/main`
- [ ] Code pulled on server
- [ ] Backend service restarted
- [ ] ActiveAlerts endpoint verified
- [ ] Dashboard verification complete










