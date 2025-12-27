#!/bin/bash
# Script to update TELEGRAM_CHAT_ID to point to Hilovivo-alerts channel

set -e

ENV_FILE="${1:-.env.aws}"

echo "🔧 Fix Telegram Channel Configuration"
echo ""
echo "This script will update TELEGRAM_CHAT_ID in ${ENV_FILE} to point to Hilovivo-alerts channel"
echo ""

# Check if file exists
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: ${ENV_FILE} not found"
    echo ""
    echo "Usage: $0 [.env.aws]"
    echo "  If no file specified, defaults to .env.aws"
    exit 1
fi

# Get current chat ID
CURRENT_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'" || echo "")

if [ -z "$CURRENT_CHAT_ID" ]; then
    echo "⚠️  Warning: TELEGRAM_CHAT_ID not found in ${ENV_FILE}"
    echo ""
    echo "Please provide the chat ID for the Hilovivo-alerts channel:"
    read -p "Chat ID: " NEW_CHAT_ID
    
    if [ -z "$NEW_CHAT_ID" ]; then
        echo "❌ Error: Chat ID cannot be empty"
        exit 1
    fi
    
    # Add TELEGRAM_CHAT_ID if it doesn't exist
    echo "" >> "$ENV_FILE"
    echo "TELEGRAM_CHAT_ID=${NEW_CHAT_ID}" >> "$ENV_FILE"
    echo "✅ Added TELEGRAM_CHAT_ID=${NEW_CHAT_ID} to ${ENV_FILE}"
else
    echo "Current TELEGRAM_CHAT_ID: ${CURRENT_CHAT_ID}"
    echo ""
    echo "Please provide the chat ID for the Hilovivo-alerts channel:"
    read -p "New Chat ID (press Enter to keep current): " NEW_CHAT_ID
    
    if [ -z "$NEW_CHAT_ID" ]; then
        echo "ℹ️  Keeping current chat ID: ${CURRENT_CHAT_ID}"
        exit 0
    fi
    
    # Update TELEGRAM_CHAT_ID
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i.bak "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${NEW_CHAT_ID}|" "$ENV_FILE"
    else
        # Linux
        sed -i "s|^TELEGRAM_CHAT_ID=.*|TELEGRAM_CHAT_ID=${NEW_CHAT_ID}|" "$ENV_FILE"
    fi
    
    echo "✅ Updated TELEGRAM_CHAT_ID to ${NEW_CHAT_ID} in ${ENV_FILE}"
fi

echo ""
echo "📝 To get the chat ID for Hilovivo-alerts channel:"
echo "   1. Add your bot to the Hilovivo-alerts channel"
echo "   2. Make your bot an admin in the channel"
echo "   3. Send a test message in the channel"
echo "   4. Get updates: https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates"
echo "   5. Look for the chat ID (usually negative number like -1001234567890)"
echo ""
echo "🔄 Next steps:"
echo "   1. Restart the backend service:"
echo "      docker compose --profile aws restart backend-aws"
echo ""
echo "   2. Restart the market-updater service:"
echo "      docker compose --profile aws restart market-updater-aws"
echo ""
echo "   3. Verify the configuration:"
echo "      docker compose --profile aws exec backend-aws env | grep TELEGRAM_CHAT_ID"

