#!/bin/bash
# Run audit script via AWS SSM (simpler version)

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Running Audit via AWS SSM"
echo "============================"
echo ""

# Verify AWS CLI is configured
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

# Run audit
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/automated-trading-platform\",
    \"CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker ps -q --filter name=backend-aws | head -1)\",
    \"if [ -z \\\"$CONTAINER\\\" ]; then CONTAINER=$(docker ps --format '{{.Names}}' | grep backend | head -1); fi\",
    \"echo Container: $CONTAINER\",
    \"echo Running audit...\",
    \"docker exec $CONTAINER python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24 --output docs/reports/no-alerts-no-trades-audit.md || echo Audit failed\",
    \"echo Audit report:\",
    \"docker exec $CONTAINER cat docs/reports/no-alerts-no-trades-audit.md | head -50 || echo Report not found\"
  ]" \
  --output text \
  --query "Command.CommandId")

if [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command"
    exit 1
fi

echo "✅ Command sent. Command ID: $COMMAND_ID"
echo "⏳ Waiting for command to complete..."
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

if [ "$STATUS" = "Success" ]; then
    echo ""
    echo "✅ Audit completed successfully!"
else
    echo ""
    echo "⚠️ Command completed with status: $STATUS"
fi

