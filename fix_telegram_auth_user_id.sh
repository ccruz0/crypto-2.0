#!/bin/bash
# Helper script to add/update TELEGRAM_AUTH_USER_ID in .env.aws
# Usage: ./fix_telegram_auth_user_id.sh [.env.aws]

set -e

ENV_FILE="${1:-.env.aws}"

if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: File $ENV_FILE not found"
    echo "Usage: $0 [.env.aws]"
    exit 1
fi

echo "🔧 Fixing Telegram Authorization User ID"
echo "======================================"
echo ""
echo "This script will help you configure TELEGRAM_AUTH_USER_ID"
echo "so users can interact with the bot commands."
echo ""
echo "Current configuration in $ENV_FILE:"
echo "-----------------------------------"
grep -E "TELEGRAM_(CHAT_ID|AUTH_USER_ID)" "$ENV_FILE" || echo "  (not found)"
echo ""

# Get current values
CURRENT_CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'" || echo "")
CURRENT_AUTH_USER_ID=$(grep "^TELEGRAM_AUTH_USER_ID=" "$ENV_FILE" | cut -d'=' -f2 | tr -d '"' | tr -d "'" || echo "")

echo "Current values:"
echo "  TELEGRAM_CHAT_ID: ${CURRENT_CHAT_ID:-'(not set)'}"
echo "  TELEGRAM_AUTH_USER_ID: ${CURRENT_AUTH_USER_ID:-'(not set)'}"
echo ""

# Prompt for user ID
echo "Enter your Telegram User ID (or multiple IDs separated by commas):"
echo "  - Get it from @userinfobot on Telegram"
echo "  - Or check bot logs: docker compose --profile aws logs backend-aws | grep user_id"
echo ""
read -p "TELEGRAM_AUTH_USER_ID: " USER_ID

if [ -z "$USER_ID" ]; then
    echo "❌ Error: User ID cannot be empty"
    exit 1
fi

# Clean up the input (remove spaces, keep commas)
USER_ID=$(echo "$USER_ID" | tr -d ' ')

echo ""
echo "Updating $ENV_FILE..."
echo ""

# Create backup
cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
echo "✅ Backup created: ${ENV_FILE}.backup.*"

# Remove existing TELEGRAM_AUTH_USER_ID line if present
if grep -q "^TELEGRAM_AUTH_USER_ID=" "$ENV_FILE"; then
    sed -i.bak "/^TELEGRAM_AUTH_USER_ID=/d" "$ENV_FILE"
    echo "✅ Removed existing TELEGRAM_AUTH_USER_ID"
fi

# Add new TELEGRAM_AUTH_USER_ID
# Find the line with TELEGRAM_CHAT_ID and add AUTH_USER_ID after it
if grep -q "^TELEGRAM_CHAT_ID=" "$ENV_FILE"; then
    # Add after TELEGRAM_CHAT_ID line
    sed -i.bak "/^TELEGRAM_CHAT_ID=/a\\
TELEGRAM_AUTH_USER_ID=$USER_ID" "$ENV_FILE"
    echo "✅ Added TELEGRAM_AUTH_USER_ID=$USER_ID"
else
    # Add at end of file
    echo "" >> "$ENV_FILE"
    echo "TELEGRAM_AUTH_USER_ID=$USER_ID" >> "$ENV_FILE"
    echo "✅ Added TELEGRAM_AUTH_USER_ID=$USER_ID at end of file"
fi

# Clean up sed backup file
rm -f "${ENV_FILE}.bak"

echo ""
echo "✅ Configuration updated!"
echo ""
echo "New configuration:"
echo "-----------------------------------"
grep -E "TELEGRAM_(CHAT_ID|AUTH_USER_ID)" "$ENV_FILE"
echo ""
echo "Next steps:"
echo "1. Restart backend: docker compose --profile aws restart backend-aws"
echo "2. Check logs: docker compose --profile aws logs backend-aws | grep 'AUTH.*Added authorized user ID'"
echo "3. Test: Send /start to your bot in Telegram"
echo ""







