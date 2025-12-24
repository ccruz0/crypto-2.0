#!/bin/bash
# Fix Telegram authorization by updating TELEGRAM_CHAT_ID

set -e

NEW_CHAT_ID="839853931"
OLD_CHAT_ID="-5033055655"

echo "🔧 Fixing Telegram Authorization..."
echo "   Current: TELEGRAM_CHAT_ID=${OLD_CHAT_ID}"
echo "   New:     TELEGRAM_CHAT_ID=${NEW_CHAT_ID}"
echo ""

# Check if .env.aws exists
if [ -f ".env.aws" ]; then
    echo "📝 Updating .env.aws..."
    
    # Remove old TELEGRAM_CHAT_ID line if exists
    sed -i.bak "/^TELEGRAM_CHAT_ID=/d" .env.aws
    
    # Add new TELEGRAM_CHAT_ID
    echo "TELEGRAM_CHAT_ID=${NEW_CHAT_ID}" >> .env.aws
    
    echo "✅ Updated .env.aws"
    echo ""
    echo "New TELEGRAM_CHAT_ID in .env.aws:"
    grep "TELEGRAM_CHAT_ID" .env.aws
else
    echo "⚠️  .env.aws not found, creating it..."
    echo "TELEGRAM_CHAT_ID=${NEW_CHAT_ID}" > .env.aws
    echo "✅ Created .env.aws with TELEGRAM_CHAT_ID=${NEW_CHAT_ID}"
fi

echo ""
echo "🔄 Restarting backend-aws..."
docker compose --profile aws restart backend-aws

echo ""
echo "⏳ Waiting for container to restart..."
sleep 10

echo ""
echo "✅ Fix applied! Test /start in Telegram now."
echo ""
echo "📊 Verify in logs:"
echo "   docker compose --profile aws logs backend-aws | grep -i 'AUTH.*Authorized'"
