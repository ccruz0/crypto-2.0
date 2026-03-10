#!/bin/bash
INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Checking Backend Logs for Quantity Formatting"
echo "================================================"
echo ""

aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","docker compose --profile aws logs --tail=200 backend-aws | grep -E \"(QUANTITY_FORMAT|quantity|DOT_USDT|SELL order|Invalid quantity)\" || docker compose --profile aws logs --tail=200 backend-aws"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' > /tmp/command_id.txt

COMMAND_ID=$(cat /tmp/command_id.txt)
echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 10 seconds..."
sleep 10

aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query 'StandardOutputContent' \
    --output text 2>&1 | grep -A 10 -B 10 "QUANTITY_FORMAT\|DOT_USDT\|SELL" | head -50
