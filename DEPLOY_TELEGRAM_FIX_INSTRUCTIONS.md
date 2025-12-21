# Deploy Telegram Alerts Fix - Quick Instructions

## Quick Deploy (On AWS Server)

Run this single command to deploy the fix:

```bash
cd /home/ubuntu/automated-trading-platform && \
git pull && \
docker-compose restart market-updater-aws && \
echo "✅ Deployment complete! Monitor logs with: docker-compose logs -f market-updater-aws | grep TELEGRAM"
```

Or use the deployment script:

```bash
cd /home/ubuntu/automated-trading-platform
./deploy_telegram_alerts_fix.sh
```

## Step-by-Step Instructions

### 1. Deploy the Fix

```bash
# SSH into your AWS server
ssh -i your-key.pem ubuntu@your-aws-ip

# Navigate to project directory
cd /home/ubuntu/automated-trading-platform

# Pull latest changes
git pull

# Restart the market-updater-aws service
docker-compose restart market-updater-aws
```

### 2. Monitor Logs

**Option A: Use the monitoring script (colorized output)**
```bash
./monitor_telegram_logs.sh
```

**Option B: Direct log monitoring**
```bash
docker-compose logs -f market-updater-aws | grep TELEGRAM
```

**Option C: Check for blocked messages**
```bash
docker-compose logs market-updater-aws | grep TELEGRAM_BLOCKED
```

**Option D: Check for successful sends**
```bash
docker-compose logs market-updater-aws | grep TELEGRAM_SUCCESS
```

### 3. Run Diagnostic Script

To verify the configuration is correct:

```bash
docker-compose exec market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py
```

This will:
- Check all environment variables
- Verify Telegram notifier configuration
- Test sending a message to Telegram
- Provide a summary of any issues

### 4. Verify Service Status

Check that the service is running:

```bash
docker-compose ps market-updater-aws
```

Should show status as "Up" and healthy.

### 5. Wait for Next Alert

Once deployed, wait for the next trading signal to trigger. You should see:
- `[TELEGRAM_INVOKE]` - Alert send attempt
- `[TELEGRAM_GATEKEEPER]` with `RESULT=ALLOW` - Message allowed
- `[TELEGRAM_SUCCESS]` - Message sent successfully

## What to Look For in Logs

### ✅ Good Signs (Alerts Working)
```
[TELEGRAM_INVOKE] origin_param=AWS ...
[TELEGRAM_GATEKEEPER] ... RESULT=ALLOW
[TELEGRAM_SUCCESS] type=ALERT symbol=... side=BUY ...
```

### ❌ Bad Signs (Alerts Blocked)
```
[TELEGRAM_BLOCKED] Skipping Telegram send for non-AWS/non-TEST origin 'LOCAL'
[TELEGRAM_GATEKEEPER] ... RESULT=BLOCK
```

### ⚠️ Configuration Issues
```
Telegram disabled: missing env vars
RUNTIME_ORIGIN is 'LOCAL' (should be 'AWS')
```

## Troubleshooting

### If alerts still don't arrive:

1. **Check RUNTIME_ORIGIN**:
   ```bash
   docker-compose exec market-updater-aws env | grep RUNTIME_ORIGIN
   ```
   Should show: `RUNTIME_ORIGIN=AWS`

2. **Check Telegram credentials**:
   ```bash
   docker-compose exec market-updater-aws env | grep TELEGRAM
   ```
   Should show both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`

3. **Check RUN_TELEGRAM flag**:
   ```bash
   docker-compose exec market-updater-aws env | grep RUN_TELEGRAM
   ```
   Should show: `RUN_TELEGRAM=true`

4. **Verify service is using AWS profile**:
   ```bash
   docker-compose ps market-updater-aws
   ```
   The service name should be `market-updater-aws` (not `market-updater`)

5. **Check if messages are being sent but not received**:
   - Verify you're checking the correct Telegram chat
   - Check if bot was removed from chat
   - Verify chat ID matches your Telegram chat

## Quick Verification Commands

```bash
# Check service is running
docker-compose ps market-updater-aws

# Check environment variables
docker-compose exec market-updater-aws env | grep -E "RUNTIME_ORIGIN|TELEGRAM|RUN_TELEGRAM"

# Check recent Telegram activity
docker-compose logs --tail=100 market-updater-aws | grep TELEGRAM

# Run diagnostic
docker-compose exec market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py
```

## Expected Behavior After Fix

1. **Next BUY/SELL signal** triggers
2. **Signal monitor** calls `send_buy_signal()` or `send_sell_signal()`
3. **Origin is explicitly set** to "AWS" via `get_runtime_origin()`
4. **Telegram gatekeeper** allows the message (origin="AWS")
5. **Message is sent** to Telegram API
6. **Success logged** with `[TELEGRAM_SUCCESS]`
7. **Message appears** in your Telegram chat

## Files Changed

- ✅ `backend/app/services/signal_monitor.py` - Added explicit origin parameter
- ✅ `backend/scripts/diagnose_telegram_alerts.py` - New diagnostic script
- ✅ `deploy_telegram_alerts_fix.sh` - Deployment script
- ✅ `monitor_telegram_logs.sh` - Log monitoring script




