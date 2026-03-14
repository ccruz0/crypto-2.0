#!/usr/bin/env bash
# Get Telegram channel IDs from PROD (where token exists).
# Prerequisite: Post a message in the target channel first, so getUpdates sees it.
#
# Usage: ./scripts/diag/run_get_channel_id_prod.sh

set -e

INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
REGION="${REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/automated-trading-platform}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "1. Post a message in your target channel (Hilovivo-alerts)"
echo "2. Deploy first if you haven't recently (script is in backend/scripts/diag/)"
echo "3. Then run this script to fetch channel IDs from getUpdates"
echo ""
read -p "Press Enter to continue..."

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd '"$REPO_PATH"' && docker compose --profile aws exec -T backend-aws python scripts/diag/get_telegram_channel_id.py"]' \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID (waiting 25s...)"
sleep 25

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'StandardOutputContent' --output text
