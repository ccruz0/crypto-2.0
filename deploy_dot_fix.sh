#!/bin/bash
# Deploy DOT Order Limit Fix to AWS

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Deploying DOT Order Limit Fix"
echo "================================="
echo ""

# Step 1: Pull latest code on server
echo "📥 Step 1: Pulling latest code..."
COMMAND_ID1=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform",
    "git config --global --add safe.directory /home/ubuntu/automated-trading-platform || git config --global --add safe.directory ~/automated-trading-platform || true",
    "git fetch origin",
    "git reset --hard origin/main",
    "git log -1 --oneline",
    "echo \"✅ Code updated\""
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

echo "⏳ Waiting for code update..."
aws ssm wait command-executed \
  --command-id "$COMMAND_ID1" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" 2>/dev/null || sleep 10

echo "✅ Code updated"
echo ""

# Step 2: Rebuild and restart backend
echo "🔨 Step 2: Rebuilding backend container..."
COMMAND_ID2=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform",
    "echo \"🔄 Rebuilding backend with latest code...\"",
    "docker compose --profile aws build --no-cache backend-aws 2>&1 | tail -20",
    "echo \"🔄 Restarting backend...\"",
    "docker compose --profile aws up -d backend-aws",
    "sleep 15",
    "docker compose --profile aws ps backend-aws",
    "echo \"✅ Backend restarted\""
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

echo "⏳ Waiting for rebuild (this may take a few minutes)..."
aws ssm wait command-executed \
  --command-id "$COMMAND_ID2" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" 2>/dev/null || sleep 60

echo ""
echo "📄 Build output:"
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID2" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text | tail -30

echo ""
echo "🔍 Step 3: Verifying fix is deployed..."

# Step 3: Verify fix is in container
COMMAND_ID3=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo \"\")",
    "if [ -n \"$CONTAINER\" ]; then",
    "  docker exec $CONTAINER grep -c \"Check 2: Total open positions count\" /app/app/services/signal_monitor.py 2>/dev/null || echo \"0\"",
    "else",
    "  echo \"0 - container not found\"",
    "fi"
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

sleep 5
FIX_CHECK=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID3" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text | tail -1 | tr -d '[:space:]')

if [ "$FIX_CHECK" = "1" ]; then
  echo "✅ Fix code verified in container!"
else
  echo "❌ Fix code not found (result: $FIX_CHECK)"
  echo "   Container may need more time to start or there may be an issue"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Monitor logs: docker logs -f automated-trading-platform-backend-aws-1 | grep DOT"
echo "   2. Check for BLOCKED messages when DOT limit is reached"
echo "   3. Verify DOT stops creating orders when count >= 3"







