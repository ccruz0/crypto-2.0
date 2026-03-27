#!/bin/bash
# Deploy backend SL/TP fix via AWS SSM

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying Backend SL/TP Fix via AWS SSM"
echo "=========================================="
echo ""

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/crypto-2.0\",
    \"echo '📥 Pulling latest code...'\",
    \"git pull origin main || echo 'Git pull failed, continuing...'\",
    \"echo '🔨 Rebuilding backend-aws container...'\",
    \"docker compose --profile aws build backend-aws\",
    \"echo '🔄 Restarting backend-aws container...'\",
    \"docker compose --profile aws restart backend-aws\",
    \"echo '⏳ Waiting for container to be healthy...'\",
    \"sleep 10\",
    \"echo '📊 Container status:'\",
    \"docker compose --profile aws ps backend-aws\",
    \"echo ''\",
    \"echo '✅ Backend deployment complete!'\"
  ]" \
  --output text \
  --query "Command.CommandId")

echo "✅ Deployment command sent!"
echo ""
echo "Command ID: $COMMAND_ID"
echo ""
echo "To check status, run:"
echo "  aws ssm get-command-invocation \\"
echo "    --command-id $COMMAND_ID \\"
echo "    --instance-id $INSTANCE_ID \\"
echo "    --region $REGION \\"
echo "    --query 'Status' \\"
echo "    --output text"
