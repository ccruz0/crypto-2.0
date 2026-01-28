# Telegram AWS Setup - Quick Guide

**Purpose**: Quick guide to configure Telegram notifications on AWS

---

## Current Status

Check current Telegram configuration:
```bash
curl -s https://dashboard.hilovivo.com/api/health/system | jq .telegram
```

**Expected Output** (when configured):
```json
{
  "status": "PASS",
  "enabled": true,
  "chat_id_set": true,
  "bot_token_set": true,
  "run_telegram_env": true,
  "kill_switch_enabled": true,
  "last_send_ok": true
}
```

---

## Quick Setup (Automated)

**On AWS EC2 instance**:
```bash
# SSH to EC2
ssh ubuntu@47.130.143.159

# Run configuration script
cd ~/automated-trading-platform
./scripts/configure_telegram_aws.sh
```

The script will:
1. Prompt for bot token and chat ID
2. Update `.env.aws` file
3. Test the configuration
4. Restart backend service

---

## Manual Setup

### Step 1: Get Telegram Bot Token

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` command
3. Follow instructions to create a bot
4. Copy the bot token (format: `<REDACTED_TELEGRAM_TOKEN>`)

### Step 2: Get Telegram Chat ID

**For a channel/group:**
1. Add your bot to the channel/group as administrator
2. Send a message to the channel
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Look for `"chat":{"id":-1001234567890}` (usually negative number)

**For a private chat:**
1. Start a conversation with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Look for `"chat":{"id":123456789}` (positive number)

### Step 3: Configure on AWS

**SSH to EC2**:
```bash
ssh ubuntu@47.130.143.159
cd ~/automated-trading-platform
```

**Edit `.env.aws` file**:
```bash
nano .env.aws
```

**Add these lines**:
```bash
# Telegram Configuration (AWS)
TELEGRAM_BOT_TOKEN_AWS=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID_AWS=<REDACTED_TELEGRAM_CHAT_ID>
RUN_TELEGRAM=true
```

**Save and restart backend**:
```bash
docker compose --profile aws restart backend-aws
```

### Step 4: Verify Configuration

**Check health status**:
```bash
curl -s http://localhost:8002/api/health/system | jq .telegram
```

**Check backend logs**:
```bash
docker compose --profile aws logs --tail 50 backend-aws | grep TELEGRAM
```

**Expected log entries**:
```
[TELEGRAM_STARTUP] ENVIRONMENT=aws hostname=... pid=... Telegram sending controlled by hard guard in send_message()
```

---

## Troubleshooting

### Issue: `status: "FAIL"` in health check

**Check**:
1. `TELEGRAM_BOT_TOKEN_AWS` is set in `.env.aws`
2. `TELEGRAM_CHAT_ID_AWS` is set in `.env.aws`
3. `RUN_TELEGRAM=true` in `.env.aws`
4. Backend service has been restarted

**Verify**:
```bash
# Check environment variables in container
docker compose --profile aws exec backend-aws env | grep TELEGRAM

# Check .env.aws file
cat .env.aws | grep TELEGRAM
```

### Issue: Bot token invalid

**Test bot token**:
```bash
curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getMe"
```

**Expected**: `{"ok":true,"result":{"id":...,"is_bot":true,"first_name":"...","username":"..."}}`

### Issue: Chat ID not working

**Verify chat ID**:
1. Make sure bot is added to channel/group (if using channel)
2. Bot must be administrator (if using channel)
3. Send a test message to the channel/chat
4. Check `getUpdates` API response

**Test sending a message**:
```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/sendMessage" \
  -d "chat_id=<YOUR_CHAT_ID>" \
  -d "text=Test message"
```

---

## Environment Variables Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN_AWS` | Bot token from BotFather | Yes |
| `TELEGRAM_CHAT_ID_AWS` | Chat/channel ID (can be negative for channels) | Yes |
| `RUN_TELEGRAM` | Enable Telegram (`true`/`false`) | Yes |
| `TELEGRAM_AUTH_USER_ID` | Authorized user IDs for bot commands (optional) | No |

**Note**: AWS backend uses `*_AWS` suffix variables. Local development uses `*_LOCAL` suffix.

---

## Security Notes

1. **Never commit `.env.aws` to git** - it contains sensitive credentials
2. **Use AWS-specific variables** - `TELEGRAM_BOT_TOKEN_AWS` and `TELEGRAM_CHAT_ID_AWS`
3. **Don't use LOCAL credentials on AWS** - the system will block this for security

---

## Related Documentation

- **Full Setup Guide**: `TELEGRAM_SETUP.md`
- **Health Monitoring**: `docs/AWS_SYSTEM_STATUS_REVIEW_CURRENT.md`
- **Telegram Commands**: See `backend/app/services/telegram_commands.py`

---

**Last Updated**: 2026-01-08

