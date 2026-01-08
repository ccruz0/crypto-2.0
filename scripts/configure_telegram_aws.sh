#!/bin/bash
# Configure Telegram credentials for AWS deployment
# This script helps set up TELEGRAM_BOT_TOKEN_AWS and TELEGRAM_CHAT_ID_AWS

set -e

echo "🔧 Telegram Configuration for AWS"
echo "=================================="
echo ""

# Check if running on AWS
if [ -z "$EC2_HOST" ]; then
    # Try to detect AWS environment
    if [ -f ".env.aws" ]; then
        echo "📋 Found .env.aws file"
    else
        echo "⚠️  Warning: .env.aws file not found"
        echo "   This script should be run on the AWS EC2 instance"
        echo ""
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

echo ""
echo "📝 Step 1: Get Telegram Bot Token"
echo "-----------------------------------"
echo "1. Open Telegram and search for @BotFather"
echo "2. Send /newbot command"
echo "3. Follow instructions to create a bot"
echo "4. Copy the bot token (format: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz)"
echo ""
read -p "Enter your Telegram Bot Token: " BOT_TOKEN

if [ -z "$BOT_TOKEN" ]; then
    echo "❌ Bot token is required"
    exit 1
fi

echo ""
echo "📝 Step 2: Get Telegram Chat ID"
echo "-----------------------------------"
echo "For a channel/group:"
echo "1. Add your bot to the channel/group as administrator"
echo "2. Send a message to the channel"
echo "3. Visit: https://api.telegram.org/bot${BOT_TOKEN}/getUpdates"
echo "4. Look for 'chat':{'id':-1001234567890} (usually negative number)"
echo ""
echo "For a private chat:"
echo "1. Start a conversation with your bot"
echo "2. Send any message"
echo "3. Visit: https://api.telegram.org/bot${BOT_TOKEN}/getUpdates"
echo "4. Look for 'chat':{'id':123456789} (positive number)"
echo ""
read -p "Enter your Telegram Chat ID: " CHAT_ID

if [ -z "$CHAT_ID" ]; then
    echo "❌ Chat ID is required"
    exit 1
fi

echo ""
echo "📝 Step 3: Verify Configuration"
echo "-----------------------------------"
echo "Bot Token: ${BOT_TOKEN:0:10}...${BOT_TOKEN: -5}"
echo "Chat ID: $CHAT_ID"
echo ""
read -p "Is this correct? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Configuration cancelled"
    exit 1
fi

echo ""
echo "📝 Step 4: Update .env.aws file"
echo "-----------------------------------"

ENV_FILE=".env.aws"

# Check if .env.aws exists
if [ ! -f "$ENV_FILE" ]; then
    echo "⚠️  .env.aws file not found. Creating it..."
    touch "$ENV_FILE"
fi

# Backup existing file
if [ -f "$ENV_FILE" ]; then
    cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✅ Backed up existing .env.aws"
fi

# Remove existing Telegram config lines
sed -i.bak '/^TELEGRAM_BOT_TOKEN_AWS=/d' "$ENV_FILE" 2>/dev/null || true
sed -i.bak '/^TELEGRAM_CHAT_ID_AWS=/d' "$ENV_FILE" 2>/dev/null || true
sed -i.bak '/^RUN_TELEGRAM=/d' "$ENV_FILE" 2>/dev/null || true

# Add new configuration
echo "" >> "$ENV_FILE"
echo "# Telegram Configuration (AWS)" >> "$ENV_FILE"
echo "TELEGRAM_BOT_TOKEN_AWS=$BOT_TOKEN" >> "$ENV_FILE"
echo "TELEGRAM_CHAT_ID_AWS=$CHAT_ID" >> "$ENV_FILE"
echo "RUN_TELEGRAM=true" >> "$ENV_FILE"

echo "✅ Updated .env.aws file"

echo ""
echo "📝 Step 5: Test Configuration"
echo "-----------------------------------"
echo "Testing bot token..."
TEST_URL="https://api.telegram.org/bot${BOT_TOKEN}/getMe"
RESPONSE=$(curl -s "$TEST_URL" || echo "")

if echo "$RESPONSE" | grep -q '"ok":true'; then
    BOT_USERNAME=$(echo "$RESPONSE" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)
    echo "✅ Bot token is valid (Bot: @$BOT_USERNAME)"
else
    echo "⚠️  Warning: Could not verify bot token"
    echo "   Response: $RESPONSE"
fi

echo ""
echo "📝 Step 6: Restart Backend Service"
echo "-----------------------------------"
echo "To apply the changes, restart the backend service:"
echo ""
echo "  docker compose --profile aws restart backend-aws"
echo ""
read -p "Restart backend now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    docker compose --profile aws restart backend-aws
    echo "✅ Backend restarted"
    echo ""
    echo "Waiting 10 seconds for service to start..."
    sleep 10
    echo ""
    echo "Checking health status..."
    curl -s http://localhost:8002/api/health/system | python3 -m json.tool | grep -A 5 '"telegram"'
else
    echo "⚠️  Remember to restart the backend service manually"
fi

echo ""
echo "✅ Telegram configuration complete!"
echo ""
echo "📋 Next steps:"
echo "1. Verify health check: curl -s http://localhost:8002/api/health/system | jq .telegram"
echo "2. Check backend logs: docker compose --profile aws logs --tail 50 backend-aws | grep TELEGRAM"
echo "3. Test by triggering a trading signal (if applicable)"
echo ""

