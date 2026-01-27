#!/bin/bash
# Bootstrap script for local Telegram dev bot setup
# This script helps extract chat_id from a DEV bot to avoid 409 conflicts with AWS production

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

# Verify we're in the right location
if [ ! -f "$BACKEND_DIR/scripts/telegram_chat_id_doctor.py" ]; then
    echo "❌ ERROR: This script must be run from the backend directory or repo root" >&2
    echo "   Expected: $BACKEND_DIR/scripts/telegram_chat_id_doctor.py" >&2
    exit 1
fi

cd "$BACKEND_DIR"

# Check for DEV token
if [ -z "${TELEGRAM_BOT_TOKEN_DEV:-}" ]; then
    echo "❌ ERROR: TELEGRAM_BOT_TOKEN_DEV is not set" >&2
    echo "" >&2
    echo "📝 To create a dev bot:" >&2
    echo "   1. Open Telegram and search for @BotFather" >&2
    echo "   2. Send /newbot and follow instructions" >&2
    echo "   3. Copy the token and set:" >&2
    echo "      export TELEGRAM_BOT_TOKEN_DEV='your_dev_bot_token'" >&2
    echo "" >&2
    echo "💡 Using a separate dev bot avoids 409 conflicts with AWS production." >&2
    exit 1
fi

# Mask token for display
TOKEN_MASKED="${TELEGRAM_BOT_TOKEN_DEV:0:6}...${TELEGRAM_BOT_TOKEN_DEV: -4}"
echo "🔍 Using DEV bot token: $TOKEN_MASKED"
echo ""

# Step 1: Extract chat_id
echo "📱 Step 1: Extracting chat_id from dev bot..."
echo "   💡 Make sure you've sent a message to your dev bot in Telegram first!"
echo ""

OUTPUT=$(python3 scripts/telegram_chat_id_doctor.py 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo "$OUTPUT" >&2
    echo "" >&2
    echo "❌ Failed to extract chat_id" >&2
    echo "" >&2
    echo "📝 Troubleshooting:" >&2
    echo "   1. Open Telegram and search for your dev bot" >&2
    echo "   2. Press 'Start' or send /start" >&2
    echo "   3. Send a test message (e.g., 'ping')" >&2
    echo "   4. Wait 5 seconds, then rerun this script" >&2
    exit 1
fi

echo "$OUTPUT"
echo ""

# Extract chat_id from output
CHAT_ID=$(echo "$OUTPUT" | grep "^USE_THIS_CHAT_ID=" | cut -d= -f2 || true)

if [ -z "$CHAT_ID" ]; then
    echo "❌ ERROR: Could not extract chat_id from doctor script output" >&2
    echo "   Output was:" >&2
    echo "$OUTPUT" | head -20 >&2
    exit 1
fi

echo "✅ Found chat_id: $CHAT_ID"
echo ""

# Step 2: Test sendMessage
echo "📤 Step 2: Testing sendMessage with dev bot..."
echo ""

export TELEGRAM_CHAT_ID_DEV="$CHAT_ID"
SEND_OUTPUT=$(python3 scripts/telegram_send_test.py 2>&1)
SEND_EXIT=$?

if [ $SEND_EXIT -ne 0 ]; then
    echo "$SEND_OUTPUT" >&2
    echo "" >&2
    echo "❌ sendMessage test failed" >&2
    exit 1
fi

echo "$SEND_OUTPUT"
echo ""

# Success - print export commands
echo "✅ SUCCESS: Local dev bot is configured and working!"
echo ""
echo "📋 Copy these lines into your shell:"
echo ""
echo "export TELEGRAM_BOT_TOKEN_DEV=\"$TELEGRAM_BOT_TOKEN_DEV\""
echo "export TELEGRAM_CHAT_ID_DEV=\"$CHAT_ID\""
echo ""
echo "🧪 Next step: Run the end-to-end test:"
echo "   cd $BACKEND_DIR"
echo "   python3 scripts/local_e2e_alert_test.sh"
echo ""
