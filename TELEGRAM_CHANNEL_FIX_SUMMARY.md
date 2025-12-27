# Telegram Channel Configuration Fix Summary

## Issue
Alerts were being sent to the wrong Telegram channel. They should go to **Hilovivo-alerts** channel.

## Root Cause
The `TELEGRAM_CHAT_ID` environment variable in `.env.aws` is pointing to the wrong channel ID. The code uses whatever `TELEGRAM_CHAT_ID` is set to - there's no hardcoded channel routing.

## Changes Made

### 1. Code Updates
- **`backend/app/services/telegram_notifier.py`**:
  - Updated comments and logging to reference "Hilovivo-alerts" (AWS) and "Hilovivo-alerts-local" (local)
  - Added diagnostic logging to show which channel ID is configured
  - Added error logging if `TELEGRAM_CHAT_ID` is missing on AWS

- **`backend/app/services/telegram_commands.py`**:
  - Updated comment to reference correct channel names

### 2. Helper Script
- **`fix_telegram_channel.sh`**: Created script to help update `TELEGRAM_CHAT_ID` in `.env.aws`

## Next Steps (Action Required)

### Step 1: Get the Chat ID for Hilovivo-alerts Channel

1. Open Telegram and go to the **Hilovivo-alerts** channel
2. Add your bot to the channel (if not already added)
3. Make your bot an admin in the channel
4. Send a test message in the channel
5. Get the chat ID using one of these methods:

   **Method A: Using Telegram API**
   ```bash
   curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
   ```
   Look for the `"chat":{"id":` field - the chat ID will be a negative number like `-1001234567890`

   **Method B: Using @userinfobot**
   - Forward a message from the channel to @userinfobot
   - It will show you the channel ID

### Step 2: Update .env.aws on AWS Server

**Option A: Using the helper script**
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
./fix_telegram_channel.sh .env.aws
# Enter the chat ID when prompted
```

**Option B: Manual edit**
```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
nano .env.aws
# Find TELEGRAM_CHAT_ID and update it to the Hilovivo-alerts channel ID
# Example: TELEGRAM_CHAT_ID=-1001234567890
```

### Step 3: Restart Services

```bash
docker compose --profile aws restart backend-aws
docker compose --profile aws restart market-updater-aws
```

### Step 4: Verify Configuration

```bash
# Check that the new chat ID is loaded
docker compose --profile aws exec backend-aws env | grep TELEGRAM_CHAT_ID

# Check the logs to see the channel configuration
docker compose --profile aws logs backend-aws | grep TELEGRAM_CONFIG
```

You should see logs like:
```
[TELEGRAM_CONFIG] env=AWS resolved_channel=-1001234567890 label=Hilovivo-alerts ...
```

### Step 5: Test

Send a test alert or wait for the next trading signal. Verify that alerts appear in the **Hilovivo-alerts** channel.

## Verification

After updating, you can verify the fix by:

1. **Check logs**: Look for `[TELEGRAM_CONFIG]` entries that show the channel ID
2. **Check actual alerts**: Next time an alert is sent, verify it appears in Hilovivo-alerts channel
3. **Monitor logs**: Watch for any `[TELEGRAM_CONFIG] CRITICAL` errors

## Important Notes

- The channel name in the code comments is just for documentation - the actual routing is done via `TELEGRAM_CHAT_ID`
- Channel IDs for Telegram channels are always negative numbers (e.g., `-1001234567890`)
- The bot must be added to the channel and have permission to send messages
- Changes to `.env.aws` require service restart to take effect

## Troubleshooting

If alerts still go to the wrong channel:

1. **Verify chat ID**: Double-check that the chat ID in `.env.aws` matches the Hilovivo-alerts channel
2. **Check bot permissions**: Ensure the bot is an admin in the Hilovivo-alerts channel
3. **Check logs**: Look for `[TELEGRAM_CONFIG]` and `[TELEGRAM_SEND]` log entries
4. **Verify environment**: Ensure `.env.aws` is being loaded (check `docker-compose.yml` env_file configuration)

