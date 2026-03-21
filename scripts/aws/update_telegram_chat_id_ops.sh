#!/usr/bin/env bash
# Update Telegram OPS chat ID (AWS_alerts) on PROD.
# Ops channel receives: health alerts, anomalies, scheduler inactivity, system down.
# Trading channel (ATP Alerts) is updated via update_telegram_chat_id.sh.
#
# Chat IDs:
#   - Private chat: positive number (e.g. 839853931)
#   - Channel/group: negative number (e.g. -1001234567890)
#
# Usage:
#   TELEGRAM_CHAT_ID_OPS=-1001234567890 ./scripts/aws/update_telegram_chat_id_ops.sh
#   ./scripts/aws/update_telegram_chat_id_ops.sh -1001234567890

set -e

REGION="${REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/automated-trading-platform}"
INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
SSM_CHAT_ID_OPS="/automated-trading-platform/prod/telegram/chat_id_ops"

NEW_CHAT_ID="${1:-$TELEGRAM_CHAT_ID_OPS}"
if [[ -z "$NEW_CHAT_ID" ]]; then
  echo "Usage: TELEGRAM_CHAT_ID_OPS=<new_id> $0"
  echo "   or: $0 <new_chat_id>"
  echo ""
  echo "This sets the OPS channel (AWS_alerts) for health/anomaly alerts."
  echo "Trading channel (ATP Alerts): use update_telegram_chat_id.sh"
  exit 1
fi

echo "Updating Telegram OPS chat ID to: $NEW_CHAT_ID"
echo ""

if command -v aws &>/dev/null && aws sts get-caller-identity &>/dev/null 2>&1; then
  echo "Updating SSM parameter $SSM_CHAT_ID_OPS..."
  aws ssm put-parameter \
    --name "$SSM_CHAT_ID_OPS" \
    --value "$NEW_CHAT_ID" \
    --type "String" \
    --overwrite \
    --region "$REGION" || true
  echo "SSM updated."
else
  echo "Skipping SSM update (no AWS CLI or credentials)"
fi

echo ""
echo "Rendering runtime.env and restarting backend on PROD..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"set -e\",\"cd $REPO_PATH\",\"bash scripts/aws/render_runtime_env.sh 2>/dev/null || true\",\"docker compose --profile aws restart backend-aws\",\"sleep 15\",\"docker compose --profile aws exec -T backend-aws env | grep -E 'TELEGRAM_CHAT_ID' | head -3\"]" \
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
echo "Done. Ops alerts (health, anomalies) will go to AWS_alerts."
