#!/usr/bin/env bash
# Update TELEGRAM_ATP_CONTROL_CHAT_ID on PROD for ATP Control Alerts channel authorization.
# Run after obtaining the channel ID from @getidsbot (forward a message from the channel).
#
# Chat ID: Channel/group IDs are negative (e.g. -1001234567890).
#
# Usage:
#   TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890 ./scripts/aws/update_atp_control_chat_id.sh
#   ./scripts/aws/update_atp_control_chat_id.sh -1001234567890

set -e

INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
REGION="${REGION:-ap-southeast-1}"
REPO_PATH="${REPO_PATH:-/home/ubuntu/crypto-2.0}"

NEW_CHAT_ID="${1:-$TELEGRAM_ATP_CONTROL_CHAT_ID}"
if [[ -z "$NEW_CHAT_ID" ]]; then
  echo "Usage: TELEGRAM_ATP_CONTROL_CHAT_ID=<channel_id> $0"
  echo "   or: $0 <channel_id>"
  echo ""
  echo "Get channel ID: Forward a message from ATP Control Alerts to @getidsbot"
  echo ""
  echo "Example: $0 -1001234567890"
  exit 1
fi

echo "Updating TELEGRAM_ATP_CONTROL_CHAT_ID to: $NEW_CHAT_ID"
echo ""

# Update .env.aws on EC2 via SSM
echo "Updating .env.aws on PROD..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"set -e\",\"cd $REPO_PATH\",\"grep -q '^TELEGRAM_ATP_CONTROL_CHAT_ID=' .env.aws && sed -i 's|^TELEGRAM_ATP_CONTROL_CHAT_ID=.*|TELEGRAM_ATP_CONTROL_CHAT_ID=$NEW_CHAT_ID|' .env.aws || echo 'TELEGRAM_ATP_CONTROL_CHAT_ID=$NEW_CHAT_ID' >> .env.aws\",\"docker compose --profile aws restart backend-aws\",\"sleep 10\",\"docker exec automated-trading-platform-backend-aws-1 env | grep TELEGRAM_ATP_CONTROL_CHAT_ID | cut -c1-45\"]" \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting 30s..."
sleep 30

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query '[Status, StandardOutputContent]' \
  --output text

echo ""
echo "Done. Send /menu from ATP Control Alerts to validate."
