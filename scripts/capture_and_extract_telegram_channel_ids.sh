#!/usr/bin/env bash
# Capture Telegram updates (with forwarded channel messages) and extract channel IDs.
# Stops backend so updates accumulate; you must FORWARD one message from each channel
# into a chat with the bot DURING the capture window.
#
# Usage: ./scripts/capture_and_extract_telegram_channel_ids.sh
#
# Steps:
#   1. Stops backend-aws
#   2. You have 45 seconds to forward messages from: ATP Control, AWS_alerts, Claw, HILOVIVO3.0
#   3. Fetches getUpdates, saves to tmp/telegram_updates.json
#   4. Extracts channel IDs and updates secrets/runtime.env, .env.aws
#   5. Restarts backend, runs verification
set -e
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

cleanup() {
  echo ""
  echo "Restarting backend..."
  docker start automated-trading-platform-backend-aws-1 2>/dev/null || true
}
trap cleanup EXIT

echo "=============================================="
echo "FORWARD one message from EACH channel into a"
echo "chat with the bot (e.g. private chat):"
echo "  • ATP Control Alerts"
echo "  • AWS_alerts"
echo "  • Claw"
echo "  • HILOVIVO3.0"
echo ""
echo "You have 45 seconds..."
echo "=============================================="

docker stop automated-trading-platform-backend-aws-1 2>/dev/null || true
sleep 45

echo ""
echo "Fetching getUpdates..."
python3 scripts/extract_channel_ids_from_updates.py --fetch

echo ""
echo "Extracting, persisting, restarting backend, and verifying..."
python3 scripts/extract_channel_ids_from_updates.py tmp/telegram_updates.json --restart-verify || true

echo ""
echo "Done."
