# Telegram Notifications Troubleshooting Guide

## Quick Diagnosis

Run the diagnostic script to check your configuration:

```bash
# On AWS instance
cd /home/ubuntu/automated-trading-platform
docker-compose --profile aws exec backend-aws python backend/scripts/diagnose_telegram_alerts.py
```

## Common Issues and Fixes

### 1. ❌ Missing Telegram Credentials

**Symptoms:**
- Logs show: `Telegram disabled: missing env vars`
- `[TELEGRAM_GATEKEEPER]` shows `bot_token_present=False` or `chat_id_present=False`

**Fix:**
1. Ensure `.env.aws` file exists and contains:
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

2. Verify credentials are loaded:
   ```bash
   docker-compose --profile aws exec backend-aws env | grep TELEGRAM
   ```

3. Restart services:
   ```bash
   docker-compose --profile aws restart backend-aws market-updater-aws
   ```

### 2. ❌ Wrong Runtime Origin

**Symptoms:**
- Logs show: `[TELEGRAM_BLOCKED] Skipping Telegram send for non-AWS/non-TEST origin 'LOCAL'`
- `get_runtime_origin()` returns `LOCAL` instead of `AWS`

**Fix:**
1. Check `docker-compose.yml` - services must have:
   ```yaml
   backend-aws:
     environment:
       - RUNTIME_ORIGIN=AWS
   
   market-updater-aws:
     environment:
       - RUNTIME_ORIGIN=AWS
   ```

2. Verify environment variable is set:
   ```bash
   docker-compose --profile aws exec backend-aws env | grep RUNTIME_ORIGIN
   # Should show: RUNTIME_ORIGIN=AWS
   ```

3. Restart services if needed:
   ```bash
   docker-compose --profile aws restart backend-aws market-updater-aws
   ```

### 3. ❌ RUN_TELEGRAM Not Enabled

**Symptoms:**
- Logs show: `Telegram disabled via RUN_TELEGRAM flag`
- `[TELEGRAM_GATEKEEPER]` shows `enabled=False`

**Fix:**
1. Check `docker-compose.yml` - services must have:
   ```yaml
   backend-aws:
     environment:
       - RUN_TELEGRAM=true
   
   market-updater-aws:
     environment:
       - RUN_TELEGRAM=true
   ```

2. Or set in `.env.aws`:
   ```bash
   RUN_TELEGRAM=true
   ```

3. Restart services:
   ```bash
   docker-compose --profile aws restart backend-aws market-updater-aws
   ```

### 4. ❌ Services Not Running with AWS Profile

**Symptoms:**
- Services are running but using local profile
- Logs show local environment variables

**Fix:**
1. Ensure services are started with AWS profile:
   ```bash
   docker-compose --profile aws up -d backend-aws market-updater-aws
   ```

2. Verify which services are running:
   ```bash
   docker-compose ps
   # Should show backend-aws and market-updater-aws (not backend and market-updater)
   ```

### 5. ❌ Network Connectivity Issues

**Symptoms:**
- Logs show: `[TELEGRAM_ERROR]` with connection timeouts or HTTP errors
- Test message fails with network errors

**Fix:**
1. Test connectivity from container:
   ```bash
   docker-compose --profile aws exec backend-aws curl -v https://api.telegram.org
   ```

2. Check firewall rules - Telegram IP ranges should be allowed:
   - `149.154.0.0/16`
   - `91.108.0.0/16`

3. If using VPN (gluetun), ensure Telegram IPs are in `FIREWALL_OUTBOUND_SUBNETS`

### 6. ❌ Invalid Bot Token or Chat ID

**Symptoms:**
- Logs show: `[TELEGRAM_RESPONSE] status=401` (Unauthorized)
- Test message fails with authentication errors

**Fix:**
1. Verify bot token is correct:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_TOKEN>/getMe"
   ```

2. Verify chat ID is correct:
   - Send a message to your bot
   - Get updates: `curl "https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates"`
   - Look for `"chat":{"id":` in the response

3. Update `.env.aws` with correct values and restart services

## Diagnostic Checklist

Run through this checklist to identify the issue:

- [ ] **Credentials configured**: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in `.env.aws`
- [ ] **Environment variables loaded**: Services can see the credentials
- [ ] **Runtime origin is AWS**: `RUNTIME_ORIGIN=AWS` in docker-compose.yml
- [ ] **Telegram enabled**: `RUN_TELEGRAM=true` in docker-compose.yml
- [ ] **Services running**: `backend-aws` and `market-updater-aws` are running (not local versions)
- [ ] **Network connectivity**: Container can reach `api.telegram.org`
- [ ] **Bot token valid**: Bot token works with Telegram API
- [ ] **Chat ID valid**: Chat ID matches your Telegram chat

## Quick Test

Test sending a notification manually:

```bash
# On AWS instance
docker-compose --profile aws exec backend-aws python -c "
from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin
result = telegram_notifier.send_message('🧪 Test notification', origin=get_runtime_origin())
print('✅ Sent' if result else '❌ Failed')
"
```

## Check Logs

Monitor logs for Telegram-related messages:

```bash
# Backend logs
docker-compose --profile aws logs -f backend-aws | grep -i telegram

# Market updater logs
docker-compose --profile aws logs -f market-updater-aws | grep -i telegram
```

Look for these log patterns:
- `[TELEGRAM_INVOKE]` - Notification attempt started
- `[TELEGRAM_GATEKEEPER]` - Gatekeeper decision (ALLOW/BLOCK)
- `[TELEGRAM_BLOCKED]` - Notification was blocked
- `[TELEGRAM_SEND]` - Message being sent
- `[TELEGRAM_SUCCESS]` - Message sent successfully
- `[TELEGRAM_ERROR]` - Error sending message

## Still Not Working?

If all checks pass but notifications still don't work:

1. **Check alert conditions**: Ensure signals are actually being detected (check signal monitor logs)
2. **Check throttle status**: Alerts might be throttled (check `[THROTTLE]` logs)
3. **Check alert_enabled flags**: Watchlist items must have `alert_enabled=True` and `buy_alert_enabled=True` or `sell_alert_enabled=True`
4. **Check database**: Verify watchlist items are configured correctly
5. **Review recent changes**: Check git history for recent changes to notification code












