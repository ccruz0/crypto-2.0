# Quick Deployment Guide - Telegram Alerts Fix

## ⚠️ Important: Changes Must Be Committed First

The deployment script uses `git pull`, so you need to commit and push the changes first.

## Quick Steps

### 1. Commit and Push Changes (if not done)
```bash
git add backend/app/services/signal_monitor.py backend/scripts/diagnose_telegram_alerts.py
git commit -m "Fix: Add explicit origin parameter to Telegram alerts"
git push origin main
```

### 2. Deploy via SSM (Automated)
```bash
./deploy_telegram_fix_ssm.sh
```

### 3. OR Deploy Manually on AWS Server

SSH into your AWS server and run:

```bash
cd /home/ubuntu/automated-trading-platform

# Fix git ownership issue
git config --global --add safe.directory /home/ubuntu/automated-trading-platform

# Pull latest code
git pull origin main

# Find container
CONTAINER=$(docker ps --filter "name=market-updater-aws" --format "{{.Names}}" | head -1)
echo "Container: $CONTAINER"

# Copy file into container
docker cp backend/app/services/signal_monitor.py $CONTAINER:/app/app/services/signal_monitor.py

# Verify fix
docker exec $CONTAINER grep "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py && echo "✅ Fix verified"

# Restart service
docker compose --profile aws restart market-updater-aws

# Check status
sleep 5
docker ps --filter "name=market-updater-aws" --format "table {{.Names}}\t{{.Status}}"
```

## What the Fix Does

The fix adds explicit `origin="AWS"` parameter when sending alerts:
- **Before**: `telegram_notifier.send_buy_signal(...)` (no origin)
- **After**: `alert_origin = get_runtime_origin()` then `telegram_notifier.send_buy_signal(..., origin=alert_origin)`

This ensures the Telegram gatekeeper allows messages to be sent.

## Verify Deployment

After deployment, monitor logs:
```bash
docker compose --profile aws logs -f market-updater-aws | grep TELEGRAM
```

Look for:
- `[TELEGRAM_INVOKE] origin_param=AWS` ✅
- `[TELEGRAM_GATEKEEPER] ... RESULT=ALLOW` ✅
- `[TELEGRAM_SUCCESS]` ✅




