# Fix Telegram Authorization Issue

## Problem
Bot responds with "Not authorized" because:
- `TELEGRAM_CHAT_ID` is set to channel ID (`839853931` for Hilovivo-alerts channel)
- User IDs don't match channel ID, so authorization fails in private chats
- Channel ID is needed for sending alerts, but user IDs are needed for bot commands

## Solution (NEW - Recommended)
Use the new `TELEGRAM_AUTH_USER_ID` environment variable to specify authorized user IDs separately from the channel ID.

### On AWS Server:
1. Get your Telegram user ID (see methods below)
2. Edit `.env.aws`:
   ```bash
   # Channel ID for sending alerts (keep existing)
   TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
   
   # Authorized user IDs for bot commands (NEW)
   TELEGRAM_AUTH_USER_ID=your_user_id_here
   # Or multiple users: TELEGRAM_AUTH_USER_ID=123456789,987654321
   ```

3. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

4. Test:
   - Send `/start` in private chat → Should work ✅
   - Send `/start` in group chat → Should work ✅

## Getting Your User ID

**Method 1: Using @userinfobot**
1. Open Telegram and search for `@userinfobot`
2. Start a conversation - it will show your user ID

**Method 2: From Bot Logs**
```bash
docker compose --profile aws logs backend-aws | grep "user_id"
```
Look for your user_id when you send a command.

**Method 3: Using Telegram API**
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
```
Look for `"from":{"id":` in the response.

## Why This Works
The new authorization system:
1. Uses `TELEGRAM_CHAT_ID` for sending alerts to channels ✅
2. Uses `TELEGRAM_AUTH_USER_ID` for authorizing bot commands ✅
3. Checks both `chat_id` and `user_id` against authorized list

## Verification
After restart, check logs:
```bash
docker compose --profile aws logs backend-aws | grep -E "(AUTH.*Added|AUTH.*Authorized)"
```

Should see:
- `[TG][AUTH] Added authorized user ID: your_user_id`
- `[TG][AUTH] ✅ Authorized chat_id=..., user_id=...`

## Legacy Solution (Not Recommended)
If you don't want to use `TELEGRAM_AUTH_USER_ID`, you can set `TELEGRAM_CHAT_ID` to your user ID, but this will break channel alerts. The new approach is better because it separates concerns.

## See Also
- `TELEGRAM_AUTHORIZATION_FIX.md` - Complete documentation of the fix
