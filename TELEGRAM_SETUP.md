# Telegram Notifications Setup

This guide explains how to set up Telegram notifications for your automated trading platform.

## Step 1: Create a Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Start a conversation with BotFather and send the command `/newbot`
3. Follow the instructions to name your bot (e.g., "My Trading Bot")
4. BotFather will give you a **Bot Token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

## Step 2: Get Your Chat ID

1. Search for your bot in Telegram (use the username you provided)
2. Start a conversation with your bot
3. Send any message to your bot
4. Open this URL in your browser (replace `YOUR_BOT_TOKEN` with your actual token):
   ```
   https://api.telegram.org/botYOUR_BOT_TOKEN/getUpdates
   ```
5. Look for the `"chat":{"id":` field in the response
6. Copy the number after `"id":` - this is your **Chat ID**

## Step 3: Configure Environment Variables

Add these variables to your `.env.aws` file on AWS:

```bash
# Bot token from BotFather
TELEGRAM_BOT_TOKEN=your_bot_token_here

# Channel ID for sending alerts (get from channel, usually negative number)
TELEGRAM_CHAT_ID=-1001234567890

# Authorized user IDs for bot commands (comma or space-separated)
# Get your user ID using @userinfobot or from bot logs
TELEGRAM_AUTH_USER_ID=your_user_id_here
```

**Important Notes:**
- `TELEGRAM_CHAT_ID`: Used for sending alerts to channels/groups (usually a negative number)
- `TELEGRAM_AUTH_USER_ID`: Used for authorizing users to use bot commands (your personal Telegram user ID)
- You can specify multiple authorized users: `TELEGRAM_AUTH_USER_ID=123456789,987654321`

## Step 4: Deploy to AWS

Run these commands to add the environment variables to your Docker container:

```bash
# SSH into your AWS instance
ssh -i "your-key.pem" ubuntu@your-ip

# Edit the docker-compose.yml to add environment variables
cd /home/ubuntu/automated-trading-platform
nano docker-compose.yml

# Add these lines under backend -> environment:
#   - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
#   - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}

# Edit .env file
nano .env

# Add your credentials:
# TELEGRAM_BOT_TOKEN=your_token
# TELEGRAM_CHAT_ID=your_chat_id

# Restart the backend
docker-compose restart backend
```

## What Notifications Will You Receive?

1. **Buy Signal**: When 3+ buy conditions are met (RSI, MA, Volume)
2. **Buy Order Created**: When a limit buy order is placed
3. **SL/TP Orders Created**: When stop loss and take profit orders are placed automatically

## Testing

Send a test message from your bot in Telegram. If configured correctly, your bot should respond with notifications when trading signals are detected.

## Troubleshooting

- **No notifications received**: Check that both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set correctly
- **Bot not responding**: Make sure you started a conversation with your bot first
- **Check logs**: Run `docker logs automated-trading-platform_backend_1` to see if there are any errors







