#!/bin/bash
# Complete deployment and verification script for portfolio_cache fix
set -e

INSTANCE_ID="i-08726dc37133b2454"
AWS_REGION="ap-southeast-1"

echo "🚀 Portfolio Cache Fix - Complete Deployment"
echo "============================================="
echo ""

# Step 1: Deploy fix to AWS
echo "📦 Step 1: Deploying fix to AWS..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || exit 1",
    "git pull origin main || echo \"Git pull failed, continuing...\"",
    "docker compose --profile aws build backend-aws",
    "docker compose --profile aws restart backend-aws",
    "sleep 10",
    "docker logs --tail 30 backend-aws 2>&1 | grep -E \"(ERROR|Exception|Traceback|Started|Uvicorn)\" | tail -10"
  ]' \
  --region "$AWS_REGION" \
  --output text \
  --query "Command.CommandId" > /tmp/deploy_cmd.txt

DEPLOY_CMD_ID=$(cat /tmp/deploy_cmd.txt)
echo "   Command ID: $DEPLOY_CMD_ID"
echo "   Waiting for deployment..."
sleep 20

echo ""
echo "📋 Deployment logs:"
aws ssm get-command-invocation \
  --command-id "$DEPLOY_CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query "StandardOutputContent" \
  --output text

# Step 2: Enable PORTFOLIO_RECONCILE_DEBUG
echo ""
echo "🔧 Step 2: Enabling PORTFOLIO_RECONCILE_DEBUG=1..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || exit 1",
    "grep -q \"PORTFOLIO_RECONCILE_DEBUG\" docker-compose.yml || sed -i \"/SIGNALS_DUP_GUARD/a\\      - PORTFOLIO_RECONCILE_DEBUG=1\" docker-compose.yml",
    "docker compose --profile aws restart backend-aws",
    "sleep 5",
    "docker exec backend-aws env | grep PORTFOLIO_RECONCILE_DEBUG || echo \"⚠️ Env var not found in container\""
  ]' \
  --region "$AWS_REGION" \
  --output text \
  --query "Command.CommandId" > /tmp/enable_debug_cmd.txt

DEBUG_CMD_ID=$(cat /tmp/enable_debug_cmd.txt)
echo "   Command ID: $DEBUG_CMD_ID"
echo "   Waiting for restart..."
sleep 15

echo ""
echo "📋 Debug enable logs:"
aws ssm get-command-invocation \
  --command-id "$DEBUG_CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query "StandardOutputContent" \
  --output text

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next: Start SSM port-forward and test:"
echo "  aws ssm start-session --target $INSTANCE_ID --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters '{\"host\":[\"127.0.0.1\"],\"portNumber\":[\"8002\"],\"localPortNumber\":[\"8002\"]}'"
echo ""
echo "Then test:"
echo "  curl -sS http://localhost:8002/api/dashboard/state | python3 -m json.tool | head -100"

