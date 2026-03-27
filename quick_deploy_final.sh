#!/bin/bash
set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Quick Deploy: Latest Code"
echo "============================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Deploying latest code..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/crypto-2.0","git pull origin main","find backend -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true","docker compose --profile aws restart backend-aws","sleep 15","docker compose --profile aws logs --tail=30 backend-aws | grep -E \"(QUANTITY_FORMAT|quantity|Quantity)\" || docker compose --profile aws logs --tail=30 backend-aws"]' \
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
echo "📊 Deployment Status:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | tail -40

echo ""
echo "🎉 Deployment complete!"
