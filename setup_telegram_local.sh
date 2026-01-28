#!/bin/bash

# Telegram Local Setup Script
BOT_TOKEN="<REDACTED_TELEGRAM_TOKEN>"
BOT_USERNAME="@Hilovivolocalbot"

echo "🔧 Telegram Local Setup"
echo "======================"
echo ""

# Step 1: Get Chat ID
echo "Step 1: Getting your Chat ID..."
echo "Please make sure you've sent a message to $BOT_USERNAME first!"
echo ""

CHAT_ID=$(curl -s "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates" | python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    if data.get('ok') and data.get('result'):
        updates = data['result']
        if updates:
            latest = updates[-1]
            if 'message' in latest:
                chat_id = latest['message']['chat']['id']
                print(chat_id)
            else:
                print('')
        else:
            print('')
    else:
        print('')
except:
    print('')
")

if [ -z "$CHAT_ID" ]; then
    echo "❌ Could not get Chat ID automatically."
    echo ""
    echo "Please do the following:"
    echo "1. Open Telegram and search for $BOT_USERNAME"
    echo "2. Start a conversation and send any message (e.g., 'Hello')"
    echo "3. Then run this command:"
    echo "   curl -s 'https://api.telegram.org/bot${BOT_TOKEN}/getUpdates' | grep -o '\"chat\":{\"id\":[0-9-]*' | head -1 | grep -o '[0-9-]*'"
    echo ""
    echo "Or visit this URL in your browser:"
    echo "https://api.telegram.org/bot${BOT_TOKEN}/getUpdates"
    echo ""
    echo "Look for 'chat':{'id': and copy the number"
    echo ""
    read -p "Enter your Chat ID manually: " CHAT_ID
fi

if [ -z "$CHAT_ID" ]; then
    echo "❌ Chat ID is required. Exiting."
    exit 1
fi

echo "✅ Chat ID: $CHAT_ID"
echo ""

# Step 2: Configure environment variables
echo "Step 2: Configuring environment variables..."

# Check if .env.local exists, if not create it
if [ ! -f ".env.local" ]; then
    echo "Creating .env.local file..."
    touch .env.local
fi

# Add or update Telegram credentials
if grep -q "TELEGRAM_BOT_TOKEN_LOCAL" .env.local; then
    # Update existing
    sed -i.bak "s|TELEGRAM_BOT_TOKEN_LOCAL=.*|TELEGRAM_BOT_TOKEN_LOCAL=${BOT_TOKEN}|" .env.local
else
    # Add new
    echo "TELEGRAM_BOT_TOKEN_LOCAL=${BOT_TOKEN}" >> .env.local
fi

if grep -q "TELEGRAM_CHAT_ID_LOCAL" .env.local; then
    # Update existing
    sed -i.bak "s|TELEGRAM_CHAT_ID_LOCAL=.*|TELEGRAM_CHAT_ID_LOCAL=${CHAT_ID}|" .env.local
else
    # Add new
    echo "TELEGRAM_CHAT_ID_LOCAL=${CHAT_ID}" >> .env.local
fi

# Clean up backup file if created
[ -f .env.local.bak ] && rm .env.local.bak

echo "✅ Environment variables configured in .env.local"
echo ""

# Step 3: Enable kill switch via API
echo "Step 3: Enabling Telegram kill switch..."
echo ""

# Try to enable via API (if backend is running)
API_URL="${API_URL:-http://localhost:8002/api}"
RESPONSE=$(curl -s -X POST "${API_URL}/settings/telegram" \
    -H "Content-Type: application/json" \
    -d '{"enabled": true}' 2>/dev/null)

if echo "$RESPONSE" | grep -q '"enabled":true'; then
    echo "✅ Kill switch enabled via API"
else
    echo "⚠️  Could not enable kill switch via API (backend might not be running)"
    echo "   You can enable it manually:"
    echo "   1. Go to Dashboard → Signals tab"
    echo "   2. Find 'Telegram Alerts' panel"
    echo "   3. Toggle the switch to ON"
    echo ""
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Restart your backend server to load the new environment variables"
echo "2. Test the Telegram connection using the 'Send Test Message' button in the dashboard"
echo ""
echo "Configuration saved:"
echo "  Bot Token: ${BOT_TOKEN:0:20}..."
echo "  Chat ID: $CHAT_ID"
echo "  File: .env.local"


