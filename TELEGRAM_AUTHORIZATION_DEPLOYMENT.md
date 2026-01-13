# Telegram Authorization Fix - Deployment Guide

## Quick Start

### 1. Get Your Telegram User ID

**Easiest Method: Use @userinfobot**
1. Open Telegram
2. Search for `@userinfobot`
3. Start conversation - it shows your user ID immediately

**Alternative: From Bot Logs**
```bash
ssh hilovivo-aws
docker compose --profile aws logs backend-aws | grep "user_id" | tail -5
```

### 2. Configure Authorization

**Option A: Using Helper Script (Recommended)**
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
./fix_telegram_auth_user_id.sh .env.aws
# Enter your user ID when prompted
```

**Option B: Manual Edit**
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
```

Add or update:
```bash
# Channel ID for sending alerts (keep existing)
TELEGRAM_CHAT_ID=839853931

# Authorized user IDs for bot commands (NEW)
TELEGRAM_AUTH_USER_ID=your_user_id_here
```

### 3. Restart Backend

```bash
docker compose --profile aws restart backend-aws
```

### 4. Verify

```bash
# Check authorization is loaded
docker compose --profile aws logs backend-aws | grep "AUTH.*Added authorized user ID"

# Should see:
# [TG][AUTH] Added authorized user ID: your_user_id
```

### 5. Test

1. Open Telegram
2. Start conversation with your bot
3. Send `/start` or click "🚀 Start" button
4. Should see main menu ✅ (not "Not authorized")

## What Changed

### Code Changes
- ✅ Added `TELEGRAM_AUTH_USER_ID` environment variable support
- ✅ Created `_is_authorized()` helper function
- ✅ Updated all authorization checks (4 locations)
- ✅ Updated tests to use new authorization logic

### Scripts Added/Updated
- ✅ `fix_telegram_auth_user_id.sh` - Helper script to configure authorization
- ✅ `quick_telegram_diagnosis.sh` - Updated to check new authorization
- ✅ `backend/scripts/test_telegram_simple.py` - Updated to use new logic

### Documentation
- ✅ `TELEGRAM_AUTHORIZATION_FIX.md` - Complete fix documentation
- ✅ `TELEGRAM_FIXES_COMPLETE.md` - Executive summary
- ✅ `FIX_AUTHORIZATION.md` - Quick reference (updated)
- ✅ `TELEGRAM_SETUP.md` - Setup guide (updated)
- ✅ `TELEGRAM_CHANNEL_FIX_SUMMARY.md` - Added authorization note

## Configuration Reference

| Variable | Purpose | Example | Required |
|----------|---------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | Bot authentication | `123456789:ABC...` | Yes |
| `TELEGRAM_CHAT_ID` | Channel ID for alerts | `839853931` | Yes |
| `TELEGRAM_AUTH_USER_ID` | Authorized user IDs | `123456789` or `123,456,789` | Recommended |

## Multiple Users

To authorize multiple users, separate IDs with commas or spaces:

```bash
TELEGRAM_AUTH_USER_ID=123456789,987654321,555666777
```

## Troubleshooting

### Still Getting "Not authorized"?

1. **Verify user ID is correct**:
   ```bash
   # Check logs when you send a command
   docker compose --profile aws logs backend-aws -f | grep "user_id"
   ```

2. **Check environment variable**:
   ```bash
   docker compose --profile aws exec backend-aws env | grep TELEGRAM_AUTH_USER_ID
   ```

3. **Check authorization logs**:
   ```bash
   docker compose --profile aws logs backend-aws | grep -E "(AUTH|DENY)" | tail -20
   ```

4. **Verify in .env.aws**:
   ```bash
   grep TELEGRAM_AUTH_USER_ID .env.aws
   ```

### Authorization Not Loading?

1. **Check startup logs**:
   ```bash
   docker compose --profile aws logs backend-aws | grep "AUTH.*Added"
   ```

2. **Verify .env.aws is loaded**:
   ```bash
   # Check docker-compose.yml has env_file: .env.aws
   grep -A 5 "env_file:" docker-compose.yml | grep ".env.aws"
   ```

3. **Restart service**:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

## Verification Commands

### Check Configuration
```bash
# On AWS server
docker compose --profile aws exec backend-aws env | grep TELEGRAM
```

### Check Authorization Logs
```bash
docker compose --profile aws logs backend-aws | grep -E "(AUTH.*Added|AUTH.*Authorized|DENY)" | tail -30
```

### Test Authorization
```bash
# Send /start to bot, then check logs
docker compose --profile aws logs backend-aws -f | grep -E "(AUTH|DENY|user_id)"
```

## Expected Log Output

### On Startup
```
[TG][AUTH] Added authorized user ID: 123456789
```

### On Command (Authorized)
```
[TG][AUTH] ✅ Authorized chat_id=123456789, user_id=123456789, AUTH_CHAT_ID=839853931, AUTHORIZED_USER_IDS={'123456789'} for command=/start
```

### On Command (Denied)
```
[TG][DENY] chat_id=999888777, user_id=999888777, AUTH_CHAT_ID=839853931, AUTHORIZED_USER_IDS={'123456789'}, command=/start
```

## Rollback

If you need to rollback:

1. Remove `TELEGRAM_AUTH_USER_ID` from `.env.aws`
2. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```
3. System will fall back to using `TELEGRAM_CHAT_ID` (may not work if it's a channel ID)

## Related Files

- `TELEGRAM_AUTHORIZATION_FIX.md` - Complete technical documentation
- `TELEGRAM_FIXES_COMPLETE.md` - Executive summary
- `fix_telegram_auth_user_id.sh` - Helper script
- `backend/app/services/telegram_commands.py` - Main code changes

## Support

If issues persist:
1. Check all logs: `docker compose --profile aws logs backend-aws | grep -i telegram`
2. Verify bot token is valid
3. Verify bot has permission in channel (for alerts)
4. Check that user ID is correct (use @userinfobot)








