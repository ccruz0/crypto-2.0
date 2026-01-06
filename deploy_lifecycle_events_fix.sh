#!/bin/bash
# Deploy lifecycle events fixes via AWS SSM

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying Lifecycle Events Fixes via AWS SSM"
echo "================================================"
echo ""

# Verify AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📦 Deploying to AWS instance: $INSTANCE_ID"
echo ""

# Deploy fixes
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/automated-trading-platform\",
    \"if [ ! -d /home/ubuntu/automated-trading-platform ]; then echo '❌ Cannot find project directory'; exit 1; fi\",
    \"echo '📥 Pulling latest code...'\",
    \"export HOME=/home/ubuntu\",
    \"git config --global --add safe.directory /home/ubuntu/automated-trading-platform || true\",
    \"git config --global user.name 'Deploy Script' || true\",
    \"git config --global user.email 'deploy@automated-trading-platform' || true\",
    \"git fetch origin main || true\",
    \"git reset --hard origin/main || true\",
    \"git clean -fd || true\",
    \"echo '✅ Code pulled successfully'\",
    \"echo ''\",
    \"echo '🔨 Building backend container...'\",
    \"docker compose --profile aws build backend-aws || exit 1\",
    \"echo '✅ Build completed'\",
    \"echo ''\",
    \"echo '🚀 Starting backend container...'\",
    \"docker compose --profile aws up -d backend-aws || exit 1\",
    \"echo '✅ Container started'\",
    \"echo ''\",
    \"echo '⏳ Waiting 10 seconds for container to initialize...'\",
    \"sleep 10\",
    \"echo '🔄 Restarting to ensure clean state...'\",
    \"docker compose --profile aws restart backend-aws\",
    \"echo '✅ Restart completed'\",
    \"echo ''\",
    \"echo '⏳ Waiting 20 seconds for service to fully start...'\",
    \"sleep 20\",
    \"echo '🔍 Verifying deployment...'\",
    \"CONTAINER=\\\$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker ps -q --filter name=backend-aws | head -1)\",
    \"if [ -z \\\"\\\$CONTAINER\\\" ]; then CONTAINER=\\\$(docker ps --format '{{.Names}}' | grep backend | head -1); fi\",
    \"echo Container: \\\$CONTAINER\",
    \"echo ''\",
    \"echo '📊 Container status:'\",
    \"docker compose --profile aws ps backend-aws\",
    \"echo ''\",
    \"echo '📋 Recent logs (last 20 lines):'\",
    \"if [ -n \\\"\\\$CONTAINER\\\" ]; then docker logs --tail 20 \\\$CONTAINER 2>/dev/null || echo '⚠️ Could not read logs'; else echo '⚠️ Container not found'; fi\",
    \"echo ''\",
    \"echo '✅ Deployment complete!'\"
  ]" \
  --output text \
  --query "Command.CommandId")

echo "📋 Command ID: $COMMAND_ID"
echo ""
echo "⏳ Deployment in progress..."
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

