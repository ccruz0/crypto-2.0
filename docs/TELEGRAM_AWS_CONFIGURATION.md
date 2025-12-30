# Telegram AWS Configuration Guide

## Overview

Telegram alerts are **only enabled on AWS** and must be configured with specific environment variables. This document provides setup, verification, and troubleshooting steps.

## Configuration Requirements

### AWS Environment Variables

**Required:**
- `ENVIRONMENT=aws` - Must be set to enable Telegram
- `TELEGRAM_BOT_TOKEN` - Bot token from BotFather
- `TELEGRAM_CHAT_ID_AWS` - AWS Telegram chat ID (required, no fallback)

**Where to set:**
1. **`.env.aws` file** (recommended for AWS deployment):
   ```
   ENVIRONMENT=aws
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID_AWS=your_chat_id_here
   ```

2. **docker-compose.yml** (for the `backend-aws` service):
   ```yaml
   environment:
     - ENVIRONMENT=aws
   env_file:
     - .env.aws  # Loads TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID_AWS
   ```

### Local/Test Environments

**Behavior:**
- When `ENVIRONMENT != "aws"`: Telegram is **disabled**
- No fallback to legacy `TELEGRAM_CHAT_ID`
- No alerts will be sent (safeguard)

## Verification Steps

### 1. Verify Environment Variables

**On AWS server:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws exec -T backend-aws env | grep -E "TELEGRAM|ENVIRONMENT" | sort'
```

**Expected output:**
```
ENVIRONMENT=aws
TELEGRAM_BOT_TOKEN=<present>
TELEGRAM_CHAT_ID_AWS=<your_chat_id>
```

### 2. Verify Container Status

**Check exactly one backend container:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws ps backend-aws'
```

**Expected:**
- One container running
- Status: `Up ... (healthy)`

### 3. Verify Telegram Startup Log

**Check startup configuration:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs backend-aws | grep -E "\[TELEGRAM_STARTUP\]" | head -1'
```

**Expected format:**
```
[TELEGRAM_STARTUP] ENVIRONMENT=aws APP_ENV=aws hostname=<hostname> pid=<pid> telegram_enabled=True bot_token_present=True chat_id_present=True chat_id_last4=****<last4>
```

### 4. Verify Active Sending

**Check recent Telegram sends:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs -n 200 backend-aws | grep -E "TELEGRAM_SEND|TELEGRAM_RESPONSE|TELEGRAM_SECURITY|TELEGRAM_STARTUP"'
```

**Expected logs (production):**
- `[TELEGRAM_STARTUP]` - Appears once at container start
- `[TELEGRAM_SEND]` - For each alert sent
- `[TELEGRAM_RESPONSE] status=200` - Successful sends
- `[TELEGRAM_SECURITY]` - Only if misconfigured (error condition)

**Example successful send:**
```
[TELEGRAM_SEND] type=ALERT symbol=ETH_USDT side=BUY chat_id=839853931 origin=AWS message_len=256
[TELEGRAM_RESPONSE] status=200 RESULT=SUCCESS message_id=12345
```

### 5. Verify No Security Errors

**Check for misconfiguration:**
```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws logs backend-aws | grep "TELEGRAM_SECURITY"'
```

**Expected:**
- No output (no errors = correctly configured)

**If errors appear:**
- `TELEGRAM_CHAT_ID_AWS not set!` → Add to `.env.aws`
- `chat_id mismatch!` → Ensure `TELEGRAM_CHAT_ID_AWS` matches expected value

## Getting Your Telegram Chat ID

### Method 1: Using getUpdates (Bot API)

1. Get your bot token from BotFather
2. Call:
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
   ```
3. Send a message to your bot
4. Call getUpdates again - the `chat.id` in the response is your chat ID

### Method 2: Using @userinfobot

1. Start a chat with [@userinfobot](https://t.me/userinfobot) on Telegram
2. Send any message
3. The bot will reply with your user ID (this is your chat ID for private chats)

### Method 3: From Telegram Web

1. Open [web.telegram.org](https://web.telegram.org)
2. Go to your chat with the bot
3. Check the URL: `https://web.telegram.org/k/#-<CHAT_ID>`
   - The number after `#-` is your chat ID (include the minus sign if present)

## Deployment Commands

### Full Deployment

```bash
# 1. SSH to AWS server
ssh hilovivo-aws

# 2. Navigate to project
cd /home/ubuntu/automated-trading-platform

# 3. Pull latest code (if needed)
git pull

# 4. Ensure .env.aws has correct values
cat .env.aws | grep -E "TELEGRAM|ENVIRONMENT"

# 5. Rebuild and restart backend
docker compose --profile aws up -d --build backend-aws

# 6. Wait for container to start (30 seconds)
sleep 30

# 7. Verify logs
docker compose --profile aws logs -n 200 backend-aws | grep -E "TELEGRAM_SEND|TELEGRAM_RESPONSE|TELEGRAM_SECURITY|TELEGRAM_STARTUP"
```

### Quick Restart (if code unchanged)

```bash
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws'
```

## Troubleshooting

### Telegram Not Sending

1. **Check ENVIRONMENT:**
   ```bash
   docker compose --profile aws exec -T backend-aws env | grep ENVIRONMENT
   ```
   Must be: `ENVIRONMENT=aws`

2. **Check credentials:**
   ```bash
   docker compose --profile aws exec -T backend-aws env | grep TELEGRAM
   ```
   Must have: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID_AWS`

3. **Check startup log:**
   ```bash
   docker compose --profile aws logs backend-aws | grep TELEGRAM_STARTUP
   ```
   Look for: `telegram_enabled=True`

4. **Check for errors:**
   ```bash
   docker compose --profile aws logs backend-aws | grep TELEGRAM_SECURITY
   ```

### Multiple Containers Running

**Check:**
```bash
docker compose --profile aws ps backend-aws
```

**Fix:**
```bash
docker compose --profile aws down backend-aws
docker compose --profile aws up -d backend-aws
```

### Wrong Chat ID

**Symptoms:**
- Messages not received
- `[TELEGRAM_SECURITY]` errors in logs

**Fix:**
1. Verify chat ID using methods above
2. Update `.env.aws`:
   ```
   TELEGRAM_CHAT_ID_AWS=<correct_chat_id>
   ```
3. Restart container:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

## Architecture Notes

### Single Source Enforcement

- **Only one backend container** should run on AWS
- All Telegram sends go through `TelegramNotifier.send_message()`
- No direct API calls bypass the notifier (except `telegram_commands.py` which is receive-only)

### Bypass Verification

**Confirm no direct Telegram API calls in production code:**
```bash
grep -r "api.telegram.org.*sendMessage" backend/app --include="*.py" | grep -v "__pycache__" | grep -v "telegram_commands.py"
```

**Expected:** Only in `telegram_notifier.py` (centralized)

**Trading alerts:**
- Trading alerts (`send_executed_order`) are called only from `exchange_sync.py`
- `telegram_commands.py` does NOT send trading alerts (only command responses)

### Logging

**Production logs (INFO level):**
- `[TELEGRAM_STARTUP]` - Once per container start
- `[TELEGRAM_SEND]` - Each send attempt
- `[TELEGRAM_RESPONSE]` - API response (status + message_id)
- `[TELEGRAM_SECURITY]` - Misconfiguration errors only

**Debug logs (DEBUG level, not shown by default):**
- `[TELEGRAM_BLOCKED]` - Messages blocked due to ENV != aws

## Security Rules

1. **AWS-only sending:**
   - `ENVIRONMENT=aws` required
   - No fallback to legacy `TELEGRAM_CHAT_ID`
   - Local/test environments: `telegram_enabled=False` always

2. **Chat ID validation:**
   - When `ENVIRONMENT=aws`: Must have `TELEGRAM_CHAT_ID_AWS`
   - Mismatch or missing: Telegram disabled with error log

3. **Single instance:**
   - Only one backend container allowed
   - Prevents duplicate alerts

## Maintenance Checklist

- [ ] Verify `TELEGRAM_CHAT_ID_AWS` is set in `.env.aws`
- [ ] Verify `ENVIRONMENT=aws` in docker-compose.yml
- [ ] Verify exactly one backend container running
- [ ] Check startup log shows `telegram_enabled=True`
- [ ] Monitor for `[TELEGRAM_SECURITY]` errors
- [ ] Verify messages are received in correct Telegram chat
- [ ] Confirm no duplicate alerts (fill-only logic active)

