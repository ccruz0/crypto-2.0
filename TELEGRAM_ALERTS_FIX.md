# Telegram Alerts Not Being Received - Fix Applied

## Problem
Alerts should be sent to Telegram but nothing is received, even though the dashboard shows messages in the "Throttle (Mensajes Enviados)" table.

## Root Cause Analysis

The issue was identified in the alert sending flow:

1. **Signal Monitor** (`signal_monitor.py`) calls `telegram_notifier.send_buy_signal()` and `telegram_notifier.send_sell_signal()` without explicitly passing the `origin` parameter.

2. **Telegram Notifier** (`telegram_notifier.py`) has a gatekeeper that only allows messages to be sent if `origin` is "AWS" or "TEST". If `origin=None`, it calls `get_runtime_origin()` which checks the `RUNTIME_ORIGIN` environment variable.

3. **Runtime Origin** must be set to "AWS" for alerts to be sent. If it's "LOCAL" or not set, alerts are blocked.

## Fixes Applied

### 1. Updated `signal_monitor.py`
- Added import: `from app.core.runtime import get_runtime_origin`
- Modified `send_buy_signal()` call to explicitly pass `origin=get_runtime_origin()`
- Modified `send_sell_signal()` call to explicitly pass `origin=get_runtime_origin()`

This ensures that the runtime origin is explicitly checked and passed to the Telegram notifier.

### 2. Created Diagnostic Script
Created `backend/scripts/diagnose_telegram_alerts.py` to help diagnose Telegram configuration issues:
- Checks environment variables (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RUNTIME_ORIGIN, etc.)
- Verifies Settings object configuration
- Checks runtime origin detection
- Tests Telegram notifier initialization
- Attempts to send a test message

## Verification Steps

### 1. Check Docker Compose Configuration
Verify that `market-updater-aws` service has:
```yaml
environment:
  - RUNTIME_ORIGIN=AWS
  - RUN_TELEGRAM=true
  - APP_ENV=aws
```

### 2. Check Environment Variables
On the AWS server, verify `.env.aws` contains:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

### 3. Run Diagnostic Script
On the AWS server, run:
```bash
cd /home/ubuntu/automated-trading-platform
docker-compose exec market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py
```

Or if running locally:
```bash
python3 backend/scripts/diagnose_telegram_alerts.py
```

### 4. Check Backend Logs
Look for these log messages:
- `[TELEGRAM_INVOKE]` - Shows when Telegram send is attempted
- `[TELEGRAM_GATEKEEPER]` - Shows gatekeeper decision (ALLOW/BLOCK)
- `[TELEGRAM_BLOCKED]` - Shows if message was blocked (non-AWS origin)
- `[TELEGRAM_SUCCESS]` - Shows successful sends
- `[TELEGRAM_ERROR]` - Shows errors

### 5. Verify Service is Running
Check that `market-updater-aws` service is running:
```bash
docker-compose ps market-updater-aws
```

## Common Issues and Solutions

### Issue: RUNTIME_ORIGIN is "LOCAL"
**Symptom**: Logs show `[TELEGRAM_BLOCKED]` with origin=LOCAL

**Solution**: 
1. Check `docker-compose.yml` - ensure `market-updater-aws` has `RUNTIME_ORIGIN=AWS`
2. Restart the service: `docker-compose restart market-updater-aws`

### Issue: Telegram Notifier Disabled
**Symptom**: Diagnostic script shows `Enabled: False`

**Solution**:
1. Check `RUN_TELEGRAM` environment variable is set to `true`
2. Check `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set
3. Restart the service

### Issue: 500 Error on Dashboard
**Symptom**: Dashboard shows "HTTP error! status: 500"

**Solution**:
1. Check backend logs for the actual error
2. Verify database connection
3. Check if backend service is healthy: `docker-compose ps backend-aws`

### Issue: Messages in Throttle Table but Not in Telegram
**Symptom**: Dashboard shows messages in "Throttle (Mensajes Enviados)" but Telegram chat is empty

**Possible Causes**:
1. Messages were sent but then deleted/archived in Telegram
2. Wrong Telegram chat ID configured
3. Bot was blocked or removed from chat
4. Messages were sent to a different Telegram chat

**Solution**:
1. Verify the correct `TELEGRAM_CHAT_ID` is configured
2. Check if you're looking at the correct Telegram chat
3. Verify the bot is still in the chat and not blocked
4. Check Telegram bot logs for delivery status

## Next Steps

1. **Deploy the fix**:
   ```bash
   # On AWS server
   cd /home/ubuntu/automated-trading-platform
   git pull
   docker-compose restart market-updater-aws
   ```

2. **Monitor logs**:
   ```bash
   docker-compose logs -f market-updater-aws | grep TELEGRAM
   ```

3. **Wait for next alert** and verify it's received in Telegram

4. **If still not working**, run the diagnostic script and check the output

## Files Changed

- `backend/app/services/signal_monitor.py` - Added explicit origin parameter to alert calls
- `backend/scripts/diagnose_telegram_alerts.py` - New diagnostic script

## Related Documentation

- `TELEGRAM_SETUP.md` - Telegram setup guide
- `SELL_ALERT_STRATEGY_VERIFICATION.md` - Alert conditions verification
