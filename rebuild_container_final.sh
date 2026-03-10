#!/bin/bash
set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔨 Rebuilding Backend Container (Clearing Python Cache)"
echo "======================================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending rebuild command..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main || true","find backend -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true","find backend -name \"*.pyc\" -delete 2>/dev/null || true","docker compose --profile aws stop backend-aws","docker compose --profile aws build --no-cache backend-aws","docker compose --profile aws up -d backend-aws","sleep 20","docker compose --profile aws ps backend-aws","docker compose --profile aws logs --tail=50 backend-aws | grep -i quantity || docker compose --profile aws logs --tail=50 backend-aws"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 90 seconds for rebuild (this takes time)..."
sleep 90

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | tail -60

echo ""
echo "🎉 Rebuild complete!"
