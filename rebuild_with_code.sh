#!/bin/bash
set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🔨 Rebuilding Container with Latest Code"
echo "========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Rebuilding container..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git pull origin main","find backend -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true","find backend -name \"*.pyc\" -delete 2>/dev/null || true","docker compose --profile aws stop backend-aws","docker compose --profile aws build --no-cache backend-aws","docker compose --profile aws up -d backend-aws","sleep 20","docker compose --profile aws exec backend-aws grep -c \"CRITICAL: Store as string\" /app/app/services/brokers/crypto_com_trade.py || echo \"0\""]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 120 seconds for rebuild..."
sleep 120

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent]' \
    --output text 2>&1 | tail -40

echo ""
echo "🎉 Rebuild complete!"
