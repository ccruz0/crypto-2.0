#!/bin/bash
# Quick script to help find your Telegram user ID from bot logs

echo "🔍 Finding your Telegram user ID from bot logs..."
echo ""
echo "This script will check recent authorization attempts in the bot logs."
echo "Look for the 'user_id' value in the output."
echo ""

# Check if we're on AWS or local
if [ -f "docker-compose.yml" ]; then
    # Try AWS first
    if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
        echo "📋 Checking AWS backend logs..."
        echo ""
        docker compose --profile aws logs backend-aws 2>/dev/null | grep -E "(DENY|AUTH)" | tail -10 | grep -E "user_id|chat_id" | head -5
        echo ""
        echo "💡 Look for the 'user_id' number in the output above."
        echo "💡 Add it to TELEGRAM_AUTH_USER_ID in .env.aws"
    elif docker compose ps backend 2>/dev/null | grep -q "Up"; then
        echo "📋 Checking local backend logs..."
        echo ""
        docker compose logs backend 2>/dev/null | grep -E "(DENY|AUTH)" | tail -10 | grep -E "user_id|chat_id" | head -5
        echo ""
        echo "💡 Look for the 'user_id' number in the output above."
        echo "💡 Add it to TELEGRAM_AUTH_USER_ID in .env.local"
    else
        echo "❌ No backend containers running. Start the backend first, then try sending /start to your bot."
        echo ""
        echo "Alternative: Use @userinfobot in Telegram to get your user ID instantly."
    fi
else
    echo "❌ docker-compose.yml not found. Are you in the project root?"
fi

echo ""
echo "📱 Alternative: Use @userinfobot in Telegram - it shows your user ID instantly!"



