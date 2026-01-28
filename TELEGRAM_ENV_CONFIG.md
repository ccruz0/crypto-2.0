# Telegram Environment Configuration

This document explains how to configure Telegram alerts for different environments (AWS production vs local development).

## Overview

The trading platform supports **environment-aware Telegram alerts** that automatically:
- Route alerts to different Telegram channels based on environment
- Add environment prefixes `[AWS]` or `[LOCAL]` to all alert messages
- Prevent confusion between production and development alerts

## Environment Variables

### Required Variables

All environments need these variables:

```bash
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

### Environment Identifier

Set `APP_ENV` to identify the environment:

```bash
# For AWS production deployment
APP_ENV=aws

# For local development
APP_ENV=local
```

## Configuration by Environment

### AWS Production Deployment

**File:** `.env.aws` or environment variables on EC2

```bash
APP_ENV=aws
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

**Result:**
- All alerts are sent to the `Hilovivo-alerts` Telegram channel
- All messages are prefixed with `[AWS]`
- Example: `[AWS] 📊 BUY SIGNAL DETECTED...`

### Local Development

**File:** `.env.local` or `.env`

```bash
APP_ENV=local
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
```

**Result:**
- All alerts are sent to the `Hilovivo-alerts-local` Telegram channel
- All messages are prefixed with `[LOCAL]`
- Example: `[LOCAL] 📊 BUY SIGNAL DETECTED...`

## Default Behavior

If `APP_ENV` is not set:
- Defaults to `local` (with a debug log message)
- Messages are prefixed with `[LOCAL]`
- **Warning:** This may cause confusion if running on AWS without `APP_ENV=aws`

## How It Works

1. **Configuration Loading:**
   - `APP_ENV` is read from environment variables via `Settings` in `app/core/config.py`
   - `get_app_env()` helper function returns `AppEnv.AWS` or `AppEnv.LOCAL`

2. **Message Sending:**
   - All alerts route through `TelegramNotifier.send_message()`
   - This method automatically:
     - Reads `APP_ENV` via `get_app_env()`
     - Adds `[AWS]` or `[LOCAL]` prefix to the message
     - Sends to the configured `TELEGRAM_CHAT_ID`

3. **Alert Methods:**
   All alert methods use `send_message()` internally:
   - `send_buy_signal()` - Buy signal alerts
   - `send_order_created()` - Order creation notifications
   - `send_executed_order()` - Order execution notifications
   - `send_sl_tp_orders()` - Stop Loss / Take Profit order alerts
   - `send_message_with_buttons()` - Messages with inline keyboards
   - All other alert methods

## Verification

### Check Current Configuration

You can verify the environment configuration by checking the logs:

```bash
# Look for these log messages:
# "Telegram Notifier initialized" - Shows Telegram is enabled
# "APP_ENV not set, defaulting to LOCAL" - Shows default behavior
```

### Test Alert

Send a test alert and verify:
1. The message appears in the correct channel (AWS vs LOCAL)
2. The message starts with `[AWS]` or `[LOCAL]` prefix

## Troubleshooting

### Alerts Not Appearing

1. **Check environment variables:**
   ```bash
   echo $APP_ENV
   echo $TELEGRAM_BOT_TOKEN
   echo $TELEGRAM_CHAT_ID
   ```

2. **Check logs:**
   ```bash
   docker compose logs backend | grep -i telegram
   ```

3. **Verify Telegram is enabled:**
   - Look for "Telegram Notifier initialized" in logs
   - If you see "Telegram disabled: missing env vars", check your environment variables

### Wrong Channel

- Verify `TELEGRAM_CHAT_ID` matches the intended channel
- Verify `APP_ENV` is set correctly (`aws` or `local`)
- Check that the bot has permission to send messages to the channel

### Missing Prefix

- All alerts should automatically include the prefix
- If prefix is missing, check that `send_message()` is being used (not direct HTTP calls)
- Verify `APP_ENV` is set correctly

## Migration Guide

### From Single Environment to Multi-Environment

1. **Create separate Telegram channels:**
   - `Hilovivo-alerts` (for production/AWS)
   - `Hilovivo-alerts-local` (for development/local)

2. **Get chat IDs:**
   - Add bot to each channel
   - Get chat ID for each channel (use `@userinfobot` or Telegram API)

3. **Update environment files:**
   - AWS: Set `APP_ENV=aws` and `TELEGRAM_CHAT_ID=<aws_chat_id>`
   - Local: Set `APP_ENV=local` and `TELEGRAM_CHAT_ID=<local_chat_id>`

4. **Restart services:**
   ```bash
   # AWS
   docker compose restart backend-aws
   
   # Local
   docker compose restart backend
   ```

5. **Verify:**
   - Send test alerts from both environments
   - Confirm messages appear in correct channels with correct prefixes

## Code Reference

- **Configuration:** `backend/app/core/config.py` - `Settings` class with `APP_ENV`
- **Helper:** `backend/app/services/telegram_notifier.py` - `get_app_env()` function
- **Main Sender:** `backend/app/services/telegram_notifier.py` - `TelegramNotifier.send_message()`
- **Tests:** `backend/tests/test_telegram_env_prefix.py`

