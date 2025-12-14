#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Quantity Formatting Fix v2"
echo "========================================"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deployment command..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main || true","CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo \"\")","if [ -n \"$CONTAINER\" ]; then docker restart $CONTAINER; sleep 10; docker logs --tail=20 $CONTAINER; else docker compose --profile aws up -d --build backend-aws; fi"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 30 seconds..."
sleep 30

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | tail -30

echo ""
echo "🎉 Deployment complete!"
