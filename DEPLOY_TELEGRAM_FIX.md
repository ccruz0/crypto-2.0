# Telegram /start Fix - Deployment Guide

## Pre-Deployment Checklist ✅

All pre-deployment checks have passed:
- ✅ File syntax verified
- ✅ All required files present
- ✅ Key changes verified
- ✅ CLI tool imports successfully
- ✅ Docker-compose configuration checked

## Files Changed

### Modified Files
1. `backend/app/services/telegram_commands.py`
   - Enhanced startup diagnostics
   - Fixed allowed_updates
   - Added my_chat_member handling
   - Always delete webhook on startup

### New Files
2. `backend/tools/telegram_diag.py` - CLI diagnostics tool
3. `backend/app/tests/test_telegram_start.py` - Unit tests
4. `docs/telegram/telegram_start_not_responding_report.md` - Investigation report

## Deployment Steps

### 1. Review Changes
```bash
git diff backend/app/services/telegram_commands.py
git status
```

### 2. Commit Changes
```bash
git add backend/app/services/telegram_commands.py
git add backend/tools/telegram_diag.py
git add backend/app/tests/test_telegram_start.py
git add docs/telegram/telegram_start_not_responding_report.md

git commit -m "Fix Telegram /start not responding: diagnostics, webhook cleanup, single poller lock, menu restore

- Enhanced startup diagnostics with TELEGRAM_DIAGNOSTICS env flag
- Created CLI tool tools/telegram_diag.py for manual diagnostics
- Always delete webhook on startup to prevent polling conflicts
- Fixed allowed_updates to include message, my_chat_member, edited_message, callback_query
- Added my_chat_member handling for bot being added to groups
- Verified single poller lock prevents multiple consumers
- Added unit tests for /start parsing, authorization, webhook deletion
- Created comprehensive investigation report"
```

### 3. Local Testing (Optional)
```bash
# Enable diagnostics mode
export TELEGRAM_DIAGNOSTICS=1

# Start backend
docker compose --profile local up backend

# Check logs for diagnostics
docker compose logs backend | grep -i "TG_DIAG\|TG\]"

# Run CLI diagnostics
docker compose exec backend python -m tools.telegram_diag --probe-updates

# Test /start in Telegram
```

### 4. AWS Deployment

#### Option A: Docker Compose (if on AWS instance)
```bash
# Pull latest changes
git pull

# Rebuild and restart
docker compose --profile aws up -d --build backend-aws

# Check logs
docker compose --profile aws logs -f backend-aws | grep -i "TG_DIAG\|webhook\|poller"
```

#### Option B: Manual Deployment (SSH to AWS)
```bash
# 1. Copy files to AWS
scp backend/app/services/telegram_commands.py user@aws:/path/to/backend/app/services/
scp backend/tools/telegram_diag.py user@aws:/path/to/backend/tools/

# 2. Restart backend container
docker compose --profile aws restart backend-aws

# 3. Check logs
docker compose --profile aws logs -f backend-aws
```

### 5. Verify Deployment

#### Check Startup Diagnostics
```bash
docker compose --profile aws logs backend-aws | grep -i "startup diagnostics\|webhook\|TG_DIAG"
```

Expected output:
```
[TG] Running startup diagnostics...
[TG] Bot identity: username=..., id=...
[TG] Webhook info: url=None, pending_updates=0
[TG] No webhook configured (polling mode)
```

#### Run CLI Diagnostics
```bash
docker compose --profile aws exec backend-aws python -m tools.telegram_diag
```

#### Test /start Command
1. Open Telegram
2. Send `/start` to bot in private chat
3. Verify welcome message with keyboard appears
4. Test in group chat: `/start@BotName`
5. Check logs for processing:
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "start\|welcome"
   ```

### 6. Monitor for Issues

Watch logs for:
- ✅ "Poller lock acquired" - Single poller active
- ✅ "Webhook deleted successfully" - Webhook cleanup working
- ✅ "Processing /start command" - Commands being received
- ✅ "Welcome message sent" - Response working
- ❌ "Another poller is active" - Multiple consumers issue
- ❌ "getUpdates conflict (409)" - Webhook or multiple pollers
- ❌ "Not authorized" - Authorization issue

## Rollback Plan

If issues occur:

1. **Stop the backend:**
   ```bash
   docker compose --profile aws stop backend-aws
   ```

2. **Revert to previous version:**
   ```bash
   git revert HEAD
   docker compose --profile aws up -d --build backend-aws
   ```

3. **Or restore from backup:**
   ```bash
   git checkout HEAD~1 -- backend/app/services/telegram_commands.py
   docker compose --profile aws restart backend-aws
   ```

## Troubleshooting

### Bot Still Not Responding

1. **Check webhook status:**
   ```bash
   docker compose --profile aws exec backend-aws python -m tools.telegram_diag
   ```

2. **Check for multiple pollers:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "poller\|lock"
   ```

3. **Check update processing:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "get_telegram_updates\|update"
   ```

4. **Check authorization:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "AUTH\|DENY"
   ```

### Enable Enhanced Diagnostics

```bash
# Set environment variable
export TELEGRAM_DIAGNOSTICS=1

# Restart backend
docker compose --profile aws restart backend-aws

# Check enhanced logs
docker compose --profile aws logs backend-aws | grep "TG_DIAG"
```

## Success Criteria

- ✅ Bot responds to `/start` in private chat
- ✅ Bot responds to `/start` in group chat
- ✅ Welcome message with keyboard appears
- ✅ Menu buttons are functional
- ✅ No 409 conflicts in logs
- ✅ Only one poller active
- ✅ Webhook is deleted on startup

## Support

For detailed investigation, see:
- `docs/telegram/telegram_start_not_responding_report.md`

For manual diagnostics:
- `python -m tools.telegram_diag --help`

