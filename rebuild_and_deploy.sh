#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🔨 Rebuilding and Deploying Backend Container"
echo "=============================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending rebuild command..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main || true","docker compose --profile aws stop backend-aws","docker compose --profile aws build --no-cache backend-aws","docker compose --profile aws up -d backend-aws","sleep 15","docker compose --profile aws ps","docker compose --profile aws logs --tail=30 backend-aws"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 60 seconds for rebuild..."
sleep 60

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | tail -50

echo ""
echo "🎉 Rebuild complete!"
