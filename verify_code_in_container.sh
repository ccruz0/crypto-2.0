#!/bin/bash
INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Verifying Code in Container"
echo "=============================="
echo ""

aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/crypto-2.0","docker compose --profile aws exec backend-aws grep -A 5 \"CRITICAL: Store as string\" /app/app/services/brokers/crypto_com_trade.py || echo \"Code not found\""]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' > /tmp/verify_cmd.txt

COMMAND_ID=$(cat /tmp/verify_cmd.txt)
echo "✅ Command ID: $COMMAND_ID"
sleep 10

aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query 'StandardOutputContent' \
    --output text 2>&1
