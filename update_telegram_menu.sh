#!/bin/bash
# Script to rebuild and restart backend-aws with updated Telegram menu code

set -e

echo "🔧 Rebuilding backend-aws image with updated Telegram menu code..."
docker compose --profile aws build backend-aws

echo "🔄 Restarting backend-aws container..."
docker compose --profile aws up -d backend-aws

echo "⏳ Waiting for container to be ready..."
sleep 10

echo "✅ Verifying code update..."
docker compose --profile aws exec backend-aws grep -A 5 "if text.startswith(\"/start\"):" /app/app/services/telegram_commands.py | head -10

echo ""
echo "✅ Done! The Telegram menu should now show the inline buttons menu instead of the old welcome message."
echo "   Test by sending /start to the bot in Telegram."

