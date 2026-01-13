# Telegram Bot Authorization Fix

## Problem

Users were getting "⛔ Not authorized" when trying to interact with the Telegram bot, even though automated alerts were working correctly.

## Root Cause

The bot was using `TELEGRAM_CHAT_ID` (which is set to the channel ID `839853931` for Hilovivo-alerts) for both:
1. **Sending alerts to the channel** ✅ (works correctly)
2. **Authorizing users for bot commands** ❌ (fails because user IDs don't match channel ID)

When a user interacts with the bot in a private chat:
- `chat_id` = user's personal Telegram ID (e.g., `123456789`)
- `user_id` = user's personal Telegram ID (e.g., `123456789`)
- `AUTH_CHAT_ID` = channel ID (`839853931`)

Since user IDs don't match the channel ID, authorization fails.

## Solution

Added support for a separate `TELEGRAM_AUTH_USER_ID` environment variable that allows you to specify authorized user IDs separately from the channel ID.

### Changes Made

1. **New Environment Variable**: `TELEGRAM_AUTH_USER_ID`
   - Supports multiple user IDs (comma or space-separated)
   - If not set, falls back to `TELEGRAM_CHAT_ID` for backward compatibility

2. **New Authorization Helper Function**: `_is_authorized(chat_id, user_id)`
   - Checks if `chat_id` matches `AUTH_CHAT_ID` (for channel/group interactions)
   - Checks if `user_id` is in `AUTHORIZED_USER_IDS` (for private chat interactions)
   - Checks if `chat_id` is in `AUTHORIZED_USER_IDS` (for private chats where chat_id == user_id)

3. **Updated All Authorization Checks**:
   - `show_main_menu()` - uses new helper
   - `show_expected_tp_menu()` - uses new helper
   - `_handle_callback_query()` - uses new helper
   - `_handle_message()` - uses new helper

## Configuration

### Step 1: Get Your Telegram User ID

You need to find your Telegram user ID. Here are a few methods:

**Method A: Using @userinfobot**
1. Open Telegram and search for `@userinfobot`
2. Start a conversation with the bot
3. It will show you your user ID

**Method B: Using Telegram API**
1. Send a message to your bot
2. Open this URL in your browser (replace `YOUR_BOT_TOKEN` with your actual token):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
3. Look for `"from":{"id":` in the response - that's your user ID

**Method C: From Bot Logs**
Check the bot logs when you try to use a command - it will show your `user_id`:
```bash
docker compose --profile aws logs backend-aws | grep "user_id"
```

### Step 2: Update Environment Variables

**On AWS Server:**

Edit `.env.aws` and add your user ID:

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
```

Add or update:
```bash
# Channel ID for sending alerts (keep existing)
TELEGRAM_CHAT_ID=839853931

# Authorized user IDs for bot commands (comma or space-separated)
TELEGRAM_AUTH_USER_ID=123456789
# Or multiple users:
# TELEGRAM_AUTH_USER_ID=123456789,987654321,555666777
```

**For Local Development:**

Edit `.env.local`:
```bash
# Channel ID for sending alerts (local test channel)
TELEGRAM_CHAT_ID=your_local_channel_id

# Authorized user IDs for bot commands
TELEGRAM_AUTH_USER_ID=your_user_id
```

### Step 3: Restart Services

```bash
# On AWS
docker compose --profile aws restart backend-aws

# On Local
docker compose --profile local restart backend
```

### Step 4: Verify Configuration

Check the logs to see if your user ID is loaded:

```bash
# On AWS
docker compose --profile aws logs backend-aws | grep "AUTH.*Added authorized user ID"
```

You should see:
```
[TG][AUTH] Added authorized user ID: 123456789
```

### Step 5: Test

1. Open Telegram and start a conversation with your bot
2. Send `/start` or click the "🚀 Start" button
3. You should now see the main menu instead of "⛔ Not authorized"

## How It Works

### Authorization Logic

The `_is_authorized()` function checks authorization in this order:

1. **Channel/Group Check**: If `chat_id` matches `AUTH_CHAT_ID` (channel/group ID), allow
2. **User ID Check**: If `user_id` is in `AUTHORIZED_USER_IDS`, allow
3. **Private Chat Check**: If `chat_id` is in `AUTHORIZED_USER_IDS` (for private chats), allow

### Example Scenarios

**Scenario 1: User in Private Chat**
- `chat_id` = `123456789` (user's personal chat ID)
- `user_id` = `123456789` (user's Telegram user ID)
- `AUTH_CHAT_ID` = `839853931` (channel ID)
- `AUTHORIZED_USER_IDS` = `{'123456789'}`
- ✅ **Authorized** (user_id matches AUTHORIZED_USER_IDS)

**Scenario 2: User in Channel/Group**
- `chat_id` = `-1001234567890` (channel/group ID)
- `user_id` = `123456789` (user's Telegram user ID)
- `AUTH_CHAT_ID` = `-1001234567890` (same channel)
- `AUTHORIZED_USER_IDS` = `{'123456789'}`
- ✅ **Authorized** (chat_id matches AUTH_CHAT_ID)

**Scenario 3: Unauthorized User**
- `chat_id` = `999888777` (different user)
- `user_id` = `999888777` (different user)
- `AUTH_CHAT_ID` = `839853931` (channel ID)
- `AUTHORIZED_USER_IDS` = `{'123456789'}`
- ❌ **Not Authorized** (no match)

## Backward Compatibility

If `TELEGRAM_AUTH_USER_ID` is not set, the system falls back to using `TELEGRAM_CHAT_ID` as the authorized user ID. This maintains backward compatibility but may not work correctly if `TELEGRAM_CHAT_ID` is a channel ID (which it typically is).

**Recommendation**: Always set `TELEGRAM_AUTH_USER_ID` with your actual user ID(s) for proper authorization.

## Troubleshooting

### Still Getting "Not authorized"?

1. **Verify your user ID is correct**:
   ```bash
   # Check logs when you send a command
   docker compose --profile aws logs backend-aws -f | grep "user_id"
   ```

2. **Check environment variable is loaded**:
   ```bash
   docker compose --profile aws exec backend-aws env | grep TELEGRAM_AUTH_USER_ID
   ```

3. **Check authorization logs**:
   ```bash
   docker compose --profile aws logs backend-aws | grep -E "(AUTH|DENY)" | tail -20
   ```

4. **Verify the variable is in docker-compose.yml**:
   Check that `TELEGRAM_AUTH_USER_ID` is included in the environment variables section.

### Multiple Users

To authorize multiple users, separate their IDs with commas or spaces:
```bash
TELEGRAM_AUTH_USER_ID=123456789,987654321,555666777
```

## Files Modified

- `backend/app/services/telegram_commands.py`:
  - Added `AUTHORIZED_USER_IDS` parsing from `TELEGRAM_AUTH_USER_ID`
  - Added `_is_authorized()` helper function
  - Updated all authorization checks to use the helper function

## Next Steps

1. Get your Telegram user ID using one of the methods above
2. Add `TELEGRAM_AUTH_USER_ID` to `.env.aws` with your user ID
3. Restart the backend service
4. Test by sending `/start` to your bot
5. Verify you can now access the menu and commands








