#!/bin/bash
# Bootstrap script to set up local Telegram DEV bot for testing
# This script extracts chat_id from a DEV bot (separate from AWS prod bot)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$BACKEND_DIR/.." && pwd)"

# Verify we're in the right location
if [ ! -f "$BACKEND_DIR/app/main.py" ]; then
    echo "❌ ERROR: This script must be run from backend directory or repo root" >&2
    echo "   Expected: $REPO_ROOT/backend" >&2
    exit 1
fi

cd "$BACKEND_DIR"

# Check for DEV token
if [ -z "${TELEGRAM_BOT_TOKEN_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN_DEV is not set" >&2
    echo "" >&2
    echo "📝 To set up a DEV bot:" >&2
    echo "   1. Open Telegram and search for @BotFather" >&2
    echo "   2. Send /newbot and follow instructions" >&2
    echo "   3. Copy the token and run:" >&2
    echo "      export TELEGRAM_BOT_TOKEN_DEV='your_dev_bot_token'" >&2
    echo "   4. Send a message to your dev bot in Telegram" >&2
    echo "   5. Rerun this script" >&2
    exit 1
fi

echo "🔍 Using DEV bot token: ${TELEGRAM_BOT_TOKEN_DEV:0:6}...${TELEGRAM_BOT_TOKEN_DEV: -4}"
echo ""

# Run doctor script to extract chat_id
echo "📡 Polling getUpdates to extract chat_id..."
echo ""

DOCTOR_OUTPUT=$(python3 scripts/telegram_chat_id_doctor.py 2>&1)
DOCTOR_EXIT=$?

echo "$DOCTOR_OUTPUT"
echo ""

if [ $DOCTOR_EXIT -ne 0 ]; then
    echo "❌ Failed to extract chat_id" >&2
    echo "" >&2
    echo "💡 Make sure you:" >&2
    echo "   1. Sent a message to your DEV bot in Telegram" >&2
    echo "   2. The bot token is correct" >&2
    exit 1
fi

# Extract chat_id from output
CHAT_ID=$(echo "$DOCTOR_OUTPUT" | grep "^USE_THIS_CHAT_ID=" | cut -d= -f2)

if [ -z "$CHAT_ID" ]; then
    echo "❌ No chat_id found in doctor output" >&2
    echo "" >&2
    echo "💡 Make sure you sent a message to your DEV bot first" >&2
    exit 1
fi

echo "✅ Found chat_id: $CHAT_ID"
echo ""

# Test sendMessage
export TELEGRAM_CHAT_ID_DEV="$CHAT_ID"
echo "🧪 Testing sendMessage with extracted chat_id..."
echo ""

if python3 scripts/telegram_send_test.py; then
    echo ""
    echo "✅ Bootstrap complete!"
    echo ""
    echo "📋 Add these to your shell environment:"
    echo ""
    echo "export TELEGRAM_BOT_TOKEN_DEV=\"${TELEGRAM_BOT_TOKEN_DEV}\""
    echo "export TELEGRAM_CHAT_ID_DEV=\"$CHAT_ID\""
    echo ""
    echo "💡 Then run: ./scripts/local_e2e_alert_test.sh"
else
    echo ""
    echo "❌ sendMessage test failed" >&2
    echo "   Check that chat_id is correct and bot is accessible" >&2
    exit 1
fi
