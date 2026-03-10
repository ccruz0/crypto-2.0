#!/bin/bash
# Deploy frontend updates via AWS SSM

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying Frontend via AWS SSM"
echo "=================================="
echo ""

# Verify AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📦 Deploying frontend to AWS instance: $INSTANCE_ID"
echo ""

# Deploy frontend
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/automated-trading-platform\",
    \"echo '📥 Pulling latest code...'\",
    \"git config --global --add safe.directory /home/ubuntu/automated-trading-platform || true\",
    \"git pull origin main || echo 'Git pull failed, continuing...'\",
    \"echo '📦 Updating frontend submodule...'\",
    \"if [ -d frontend ]; then cd frontend; git pull origin main || echo 'Frontend git pull failed, continuing...'; cd /home/ubuntu/automated-trading-platform; else echo 'Frontend directory not found, skipping...'; fi\",
    \"echo '🔨 Rebuilding frontend-aws container...'\",
    \"docker compose --profile aws build frontend-aws\",
    \"echo '🔄 Restarting frontend-aws container...'\",
    \"docker compose --profile aws up -d frontend-aws\",
    \"echo '⏳ Waiting for container to be healthy...'\",
    \"sleep 10\",
    \"echo '📊 Container status:'\",
    \"docker compose --profile aws ps frontend-aws\",
    \"echo ''\",
    \"echo '✅ Frontend deployment complete!'\"
  ]" \
  --output text \
  --query "Command.CommandId")

echo "✅ Deployment command sent!"
echo ""
echo "Command ID: $COMMAND_ID"
echo ""
echo "To check status, run:"
echo "  ./check_deployment_status.sh $COMMAND_ID"
echo ""
echo "Or manually:"
echo "  aws ssm get-command-invocation \\"
echo "    --command-id $COMMAND_ID \\"
echo "    --instance-id $INSTANCE_ID \\"
echo "    --region $REGION \\"
echo "    --query 'Status' \\"
echo "    --output text"

