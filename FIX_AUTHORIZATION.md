# Fix Telegram Authorization Issue

## Problem
Bot responds with "Not authorized" because:
- Current `TELEGRAM_CHAT_ID=-5033055655` (group chat ID)
- Your user_id: `839853931`
- Authorization fails in private chats

## Solution
Update `TELEGRAM_CHAT_ID` to your personal user_id: `839853931`

## Steps

### On AWS Server:
1. Edit `.env.aws`:
   ```bash
   TELEGRAM_CHAT_ID=839853931
   ```

2. Restart backend:
   ```bash
   docker compose --profile aws restart backend-aws
   ```

3. Test:
   - Send `/start` in private chat → Should work ✅
   - Send `/start` in group chat → Should work ✅

## Why This Works
The authorization checks: `chat_id == AUTH_CHAT_ID OR user_id == AUTH_CHAT_ID`

- **Private chat**: `chat_id = 839853931` matches ✅
- **Group chat**: `user_id = 839853931` matches ✅

## Verification
After restart, check logs:
```bash
docker compose --profile aws logs backend-aws | grep -i "AUTH.*Authorized"
```

Should see: `[TG][AUTH] ✅ Authorized chat_id=839853931, user_id=839853931`
