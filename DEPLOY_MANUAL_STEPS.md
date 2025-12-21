# Manual Deployment Steps for Telegram Alerts Fix

Since the automated deployment script cannot connect to AWS, here are the manual steps to deploy the fix directly on your AWS server.

## Option 1: Deploy via SSH (Recommended)

### Step 1: SSH into your AWS server
```bash
ssh -i ~/.ssh/id_rsa ubuntu@54.254.150.31
# Or use your preferred SSH method
```

### Step 2: Navigate to project directory
```bash
cd ~/automated-trading-platform
# or
cd /home/ubuntu/automated-trading-platform
```

### Step 3: Pull latest changes
```bash
git pull origin main
```

### Step 4: Verify the fix is present
```bash
# Check that the import is present
grep "from app.core.runtime import get_runtime_origin" backend/app/services/signal_monitor.py && echo "✅ Import found" || echo "❌ Import missing"

# Check that origin parameter is being passed
grep "alert_origin = get_runtime_origin()" backend/app/services/signal_monitor.py && echo "✅ Origin fix found" || echo "❌ Origin fix missing"
```

### Step 5: Find the market-updater-aws container
```bash
docker ps --filter "name=market-updater-aws" --format "{{.Names}}"
```

### Step 6: Copy the file into the container
```bash
# Replace CONTAINER_NAME with the actual container name from step 5
CONTAINER_NAME=$(docker ps --filter "name=market-updater-aws" --format "{{.Names}}" | head -1)
docker cp backend/app/services/signal_monitor.py $CONTAINER_NAME:/app/app/services/signal_monitor.py
```

### Step 7: Verify the file was copied correctly
```bash
docker exec $CONTAINER_NAME grep -q "from app.core.runtime import get_runtime_origin" /app/app/services/signal_monitor.py && echo "✅ Import verified in container" || echo "❌ Import not found in container"
docker exec $CONTAINER_NAME grep -q "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py && echo "✅ Origin fix verified in container" || echo "❌ Origin fix not found in container"
```

### Step 8: Restart the service
```bash
docker compose --profile aws restart market-updater-aws
# Or if that doesn't work:
docker restart $CONTAINER_NAME
```

### Step 9: Verify service is running
```bash
sleep 5
docker ps --filter "name=market-updater-aws" --format "table {{.Names}}\t{{.Status}}"
```

### Step 10: Monitor logs
```bash
docker compose --profile aws logs -f market-updater-aws | grep TELEGRAM
```

## Option 2: One-Line Deployment (Copy-Paste Ready)

Run this entire block on your AWS server:

```bash
cd ~/automated-trading-platform && \
git pull origin main && \
CONTAINER_NAME=$(docker ps --filter "name=market-updater-aws" --format "{{.Names}}" | head -1) && \
echo "Container: $CONTAINER_NAME" && \
docker cp backend/app/services/signal_monitor.py $CONTAINER_NAME:/app/app/services/signal_monitor.py && \
docker exec $CONTAINER_NAME grep -q "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py && echo "✅ Fix verified" || echo "❌ Fix not found" && \
docker compose --profile aws restart market-updater-aws && \
sleep 5 && \
echo "✅ Deployment complete! Monitor logs with: docker compose --profile aws logs -f market-updater-aws | grep TELEGRAM"
```

## Option 3: Using Git Pull Only (If code is already committed)

If you've already committed and pushed the changes to git:

```bash
# On AWS server
cd ~/automated-trading-platform
git pull origin main
docker compose --profile aws restart market-updater-aws
```

Note: This only works if your Docker container has the code mounted as a volume. If the code is baked into the image, you'll need to rebuild.

## Verification Steps

After deployment, verify everything is working:

### 1. Check service status
```bash
docker compose --profile aws ps market-updater-aws
```

### 2. Check environment variables
```bash
docker compose --profile aws exec market-updater-aws env | grep -E "RUNTIME_ORIGIN|TELEGRAM|RUN_TELEGRAM"
```

Should show:
- `RUNTIME_ORIGIN=AWS`
- `TELEGRAM_BOT_TOKEN=...`
- `TELEGRAM_CHAT_ID=...`
- `RUN_TELEGRAM=true`

### 3. Run diagnostic script
```bash
docker compose --profile aws exec market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py
```

### 4. Monitor logs for next alert
```bash
docker compose --profile aws logs -f market-updater-aws | grep -E "TELEGRAM|alert"
```

Look for:
- `[TELEGRAM_INVOKE] origin_param=AWS` ✅
- `[TELEGRAM_GATEKEEPER] ... RESULT=ALLOW` ✅
- `[TELEGRAM_SUCCESS]` ✅

## Troubleshooting

### If container not found:
```bash
# List all containers
docker ps --format "table {{.Names}}\t{{.Status}}"

# Check if service is running with different name
docker compose --profile aws ps
```

### If file copy fails:
```bash
# Check if file exists locally
ls -la backend/app/services/signal_monitor.py

# Check container file system
docker exec $CONTAINER_NAME ls -la /app/app/services/signal_monitor.py
```

### If service won't restart:
```bash
# Check logs for errors
docker compose --profile aws logs --tail=50 market-updater-aws

# Try restarting with docker directly
docker restart $CONTAINER_NAME
```

## What Changed

The fix adds explicit `origin` parameter to alert sending:
- **Before**: `telegram_notifier.send_buy_signal(...)` (no origin)
- **After**: `alert_origin = get_runtime_origin()` then `telegram_notifier.send_buy_signal(..., origin=alert_origin)`

This ensures the Telegram gatekeeper allows the message to be sent.

## Next Steps After Deployment

1. ✅ Wait for next trading signal
2. ✅ Check Telegram chat for alert
3. ✅ Verify logs show `[TELEGRAM_SUCCESS]`
4. ✅ If still not working, run diagnostic script




