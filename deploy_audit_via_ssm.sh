#!/bin/bash
# Deploy audit fixes and run audit via AWS SSM

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying Audit Fixes via AWS SSM"
echo "===================================="
echo ""

# Verify AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📦 Deploying fixes to AWS instance: $INSTANCE_ID"
echo ""

# Deploy fixes and run audit
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/automated-trading-platform || { echo '❌ Cannot find project directory' && exit 1; }\",
    \"echo '📥 Pulling latest code...'\",
    \"git config --global --add safe.directory /home/ubuntu/automated-trading-platform || true\",
    \"git pull origin main || echo 'Git pull failed, continuing...'\",
    \"echo '🔧 Making scripts executable...'\",
    \"chmod +x deploy_audit_fixes.sh run_audit_in_production.sh 2>/dev/null || true\",
    \"echo '🚀 Deploying fixes...'\",
    \"docker compose --profile aws build backend-aws\",
    \"docker compose --profile aws up -d backend-aws\",
    \"sleep 5\",
    \"docker compose --profile aws restart backend-aws\",
    \"echo '✅ Deployment complete!'\",
    \"echo ''\",
    \"echo '⏳ Waiting 30 seconds for service to start...'\",
    \"sleep 30\",
    \"echo '🔍 Finding container name...'\",
    \"CONTAINER=\\\$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker ps -q --filter 'name=backend-aws' | head -1)\",
    \"if [ -z \\\"\\\$CONTAINER\\\" ]; then CONTAINER=\\\$(docker ps --format '{{.Names}}' | grep backend | head -1); fi\",
    \"echo 'Container: '\\\$CONTAINER\",
    \"echo '🔍 Verifying deployment...'\",
    \"docker logs \\\$CONTAINER 2>/dev/null | grep 'Signal monitor service' | tail -3 || echo '⚠️ Signal monitor service log not found'\",
    \"echo ''\",
    \"echo '📊 Running audit...'\",
    \"TIMESTAMP=\\\$(date +%Y%m%d-%H%M%S 2>/dev/null || echo 'manual')\",
    \"AUDIT_FILE=\\\"docs/reports/no-alerts-no-trades-audit-\\\$TIMESTAMP.md\\\"\",
    \"docker exec \\\$CONTAINER python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24 --output \\\$AUDIT_FILE || echo '⚠️ Audit failed'\",
    \"echo ''\",
    \"echo '📄 Audit report location:'\",
    \"docker exec \\\$CONTAINER ls -la docs/reports/no-alerts-no-trades-audit-*.md 2>/dev/null | tail -1 || echo 'Report not found'\",
    \"echo ''\",
    \"echo '💓 Checking for heartbeat (last 5):'\",
    \"docker logs \\\$CONTAINER 2>/dev/null | grep HEARTBEAT | tail -5 || echo 'No heartbeat found yet (may take ~5 minutes)'\",
    \"echo ''\",
    \"echo '🚨 Checking for global blockers:'\",
    \"docker logs \\\$CONTAINER 2>/dev/null | grep GLOBAL_BLOCKER | tail -5 || echo 'No global blockers found'\"
  ]" \
  --output text \
  --query "Command.CommandId")

if [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command"
    exit 1
fi

echo "✅ Command sent. Command ID: $COMMAND_ID"
echo ""
echo "⏳ Waiting for command to complete..."
echo "   (This may take 2-3 minutes)"
echo ""

# Wait for command to complete
aws ssm wait command-executed \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" || true

echo ""
echo "📋 Getting command output..."
echo ""

# Get command output
OUTPUT=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" \
  --output text)

ERRORS=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardErrorContent" \
  --output text)

STATUS=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "Status" \
  --output text)

echo "Status: $STATUS"
echo ""
echo "=== OUTPUT ==="
echo "$OUTPUT"
echo ""

if [ -n "$ERRORS" ]; then
    echo "=== ERRORS ==="
    echo "$ERRORS"
    echo ""
fi

if [ "$STATUS" = "Success" ]; then
    echo "✅ Deployment and audit completed successfully!"
    echo ""
    echo "📄 To view the full audit report, SSH into the server and run:"
    echo "   cat docs/reports/no-alerts-no-trades-audit-*.md | tail -1"
    echo ""
    echo "💓 To monitor heartbeat:"
    echo "   docker logs -f backend-aws | grep HEARTBEAT"
else
    echo "⚠️ Command completed with status: $STATUS"
    echo "   Check the output above for details"
fi

