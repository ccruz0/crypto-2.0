#!/bin/bash
# Script to verify Telegram channel configuration

set -e

echo "🔍 Verifying Telegram Channel Configuration"
echo ""

# Check if we're on AWS or local
if [ -f ".env.aws" ]; then
    ENV_FILE=".env.aws"
    ENV_TYPE="AWS"
elif [ -f ".env.local" ]; then
    ENV_FILE=".env.local"
    ENV_TYPE="LOCAL"
elif [ -f ".env" ]; then
    ENV_FILE=".env"
    ENV_TYPE="LOCAL"
else
    echo "❌ No .env file found"
    exit 1
fi

echo "📁 Using environment file: ${ENV_FILE} (${ENV_TYPE})"
echo ""

# Get TELEGRAM_CHAT_ID
if [ ! -f "$ENV_FILE" ]; then
    echo "❌ Error: ${ENV_FILE} not found"
    exit 1
fi

CHAT_ID=$(grep "^TELEGRAM_CHAT_ID=" "$ENV_FILE" | cut -d'=' -f2- | tr -d '"' | tr -d "'" | tr -d ' ' || echo "")

if [ -z "$CHAT_ID" ]; then
    echo "❌ TELEGRAM_CHAT_ID not found in ${ENV_FILE}"
    echo ""
    echo "💡 To fix:"
    echo "   1. Get the chat ID for Hilovivo-alerts channel"
    echo "   2. Add TELEGRAM_CHAT_ID=<chat_id> to ${ENV_FILE}"
    exit 1
fi

echo "✅ TELEGRAM_CHAT_ID found: ${CHAT_ID}"
echo ""

# Check if it's a valid channel ID format (negative number for channels)
if [[ "$CHAT_ID" =~ ^- ]]; then
    echo "✅ Chat ID format looks correct (channel ID: negative number)"
else
    echo "⚠️  Warning: Chat ID doesn't look like a channel ID (channels usually have negative IDs)"
    echo "   This might be a user ID instead of a channel ID"
fi

echo ""
echo "📋 Expected Channels:"
if [ "$ENV_TYPE" = "AWS" ]; then
    echo "   - AWS Production: Hilovivo-alerts"
else
    echo "   - Local Development: Hilovivo-alerts-local"
fi

echo ""
echo "🔍 To verify the channel is correct:"
echo "   1. Check the logs for [TELEGRAM_CONFIG] entries:"
echo "      docker compose --profile aws logs backend-aws | grep TELEGRAM_CONFIG"
echo ""
echo "   2. Send a test alert and verify it appears in the correct channel"
echo ""
echo "   3. Check recent Telegram sends:"
echo "      docker compose --profile aws logs backend-aws | grep TELEGRAM_SEND"



