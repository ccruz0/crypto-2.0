#!/usr/bin/env bash
# Update Telegram TRADING chat ID (HILOVIVO3.0) on PROD.
# Trading channel receives: signals, orders, reports, SL/TP.
# Ops channel (AWS_alerts): use update_telegram_chat_id_ops.sh
#
# Chat IDs:
#   - Private chat: positive number (e.g. 839853931)
#   - Channel/group: negative number (e.g. -1001234567890)
#
# To get channel ID: forward a channel message to @userinfobot, or:
#   curl "https://api.telegram.org/bot\${TOKEN}/getUpdates" | jq '.result[].message.chat | select(.id < 0)'
#
# Usage:
#   TELEGRAM_CHAT_ID=-1001234567890 ./scripts/aws/update_telegram_chat_id.sh
#   ./scripts/aws/update_telegram_chat_id.sh -1001234567890

set -e

INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
REGION="${REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/automated-trading-platform}"
SSM_CHAT_ID="/automated-trading-platform/prod/telegram/chat_id"

NEW_CHAT_ID="${1:-$TELEGRAM_CHAT_ID}"
if [[ -z "$NEW_CHAT_ID" ]]; then
  echo "Usage: TELEGRAM_CHAT_ID=<new_id> $0"
  echo "   or: $0 <new_chat_id>"
  echo ""
  echo "Examples:"
  echo "  TELEGRAM_CHAT_ID=-1001234567890 $0   # channel"
  echo "  $0 839853931                         # private chat"
  exit 1
fi

echo "Updating Telegram chat ID to: $NEW_CHAT_ID"
echo ""

# 1. Update SSM parameter (if AWS CLI available)
if command -v aws &>/dev/null && aws sts get-caller-identity &>/dev/null 2>&1; then
  echo "Updating SSM parameter $SSM_CHAT_ID..."
  aws ssm put-parameter \
    --name "$SSM_CHAT_ID" \
    --value "$NEW_CHAT_ID" \
    --type "String" \
    --overwrite \
    --region "$REGION" || true
  echo "SSM updated (or skipped if no access)"
else
  echo "Skipping SSM update (no AWS CLI or credentials)"
fi

# 2. Run on PROD via SSM: render runtime.env, restart backend
echo ""
echo "Rendering runtime.env and restarting backend on PROD..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"set -e\",\"cd $REPO_PATH\",\"bash scripts/aws/render_runtime_env.sh 2>/dev/null || true\",\"docker compose --profile aws restart backend-aws\",\"sleep 15\",\"docker compose --profile aws exec -T backend-aws env | grep -E 'TELEGRAM_CHAT_ID=' | head -1\"]" \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting 45s..."
sleep 45

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query '[Status, StandardOutputContent]' \
  --output text

echo ""
echo "Done. Check your Telegram chat for the next alert."
