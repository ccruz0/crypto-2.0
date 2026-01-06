#!/bin/bash
# Deploy portfolio_cache defensive fix to AWS via SSM
set -e

INSTANCE_ID="i-08726dc37133b2454"
AWS_REGION="ap-southeast-1"

echo "🚀 Deploying portfolio_cache defensive fix to AWS..."
echo "   Instance: $INSTANCE_ID"
echo ""

# Step 1: Pull latest code on AWS
echo "📥 Pulling latest code on AWS..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || { echo \"❌ Cannot find project directory\" && exit 1; }",
    "git pull origin main || { echo \"⚠️ Git pull failed, continuing...\" && exit 0; }",
    "echo \"✅ Code updated\""
  ]' \
  --region "$AWS_REGION" \
  --output text \
  --query "Command.CommandId" > /tmp/ssm_pull_cmd.txt

PULL_CMD_ID=$(cat /tmp/ssm_pull_cmd.txt)
echo "   Command ID: $PULL_CMD_ID"
echo "   Waiting for pull to complete..."
sleep 5

aws ssm get-command-invocation \
  --command-id "$PULL_CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query "StandardOutputContent" \
  --output text

# Step 2: Rebuild and restart backend-aws
echo ""
echo "🔨 Rebuilding and restarting backend-aws..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || exit 1",
    "docker compose --profile aws build backend-aws",
    "docker compose --profile aws restart backend-aws",
    "sleep 5",
    "docker logs --tail 50 backend-aws 2>&1 | tail -20"
  ]' \
  --region "$AWS_REGION" \
  --output text \
  --query "Command.CommandId" > /tmp/ssm_deploy_cmd.txt

DEPLOY_CMD_ID=$(cat /tmp/ssm_deploy_cmd.txt)
echo "   Command ID: $DEPLOY_CMD_ID"
echo "   Waiting for deployment to complete..."
sleep 15

aws ssm get-command-invocation \
  --command-id "$DEPLOY_CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query "StandardOutputContent" \
  --output text

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Enable PORTFOLIO_RECONCILE_DEBUG=1 (see docker-compose.yml or .env.aws)"
echo "2. Restart backend: docker compose --profile aws restart backend-aws"
echo "3. Test: curl http://localhost:8002/api/dashboard/state"
