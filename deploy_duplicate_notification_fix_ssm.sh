#!/bin/bash
# Deploy duplicate notification fix via AWS Session Manager (SSM)

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying duplicate notification fix vía AWS Session Manager"
echo "================================================================"
echo ""

# Verify AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📦 Deploying exchange_sync.py fix..."

# Deploy via SSM
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform\",
    \"git pull origin main || echo 'Git pull failed'\",
    \"CONTAINER=\$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker compose ps -q backend 2>/dev/null || docker ps -q --filter 'name=backend')\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then\",
    \"  echo '📋 Copying exchange_sync.py to container...'\",
    \"  docker cp backend/app/services/exchange_sync.py \\\$CONTAINER:/app/app/services/exchange_sync.py\",
    \"  echo '🔄 Restarting backend...'\",
    \"  docker compose --profile aws restart backend-aws 2>/dev/null || docker compose restart backend 2>/dev/null || docker restart \\\$CONTAINER\",
    \"  echo '✅ Backend restarted'\",
    \"  sleep 5\",
    \"  echo '📊 Recent logs:'\",
    \"  docker compose --profile aws logs --tail=30 backend-aws 2>/dev/null || docker compose logs --tail=30 backend 2>/dev/null || docker logs --tail=30 \\\$CONTAINER\",
    \"else\",
    \"  echo '❌ Backend container not found'\",
    \"  exit 1\",
    \"fi\"
  ]" \
  --output text \
  --query "Command.CommandId")

echo "📋 Command ID: $COMMAND_ID"
echo "⏳ Waiting for command to complete..."
echo ""

# Wait for command to complete
aws ssm wait command-executed \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION"

# Get command output
echo ""
echo "📊 Command Output:"
echo "=================="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "[StandardOutputContent, StandardErrorContent]" \
  --output text

echo ""
echo "✅ Deployment complete!"
echo ""
echo "The fix will prevent duplicate ORDER EXECUTED notifications."
echo "Each executed order will now only send one Telegram notification."


