#!/bin/bash
# Quick verification script for DOT order limit fix

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Verifying DOT Order Limit Fix"
echo "================================="
echo ""

echo "1️⃣ Checking recent blocked orders..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs automated-trading-platform-backend-aws-1 2>&1 | grep -i \"BLOCKED.*DOT\\|BLOCKED.*final check\" | tail -10"]' \
  --region "$REGION" \
  --output text --query "Command.CommandId" > /tmp/command_id.txt

sleep 5
COMMAND_ID=$(cat /tmp/command_id.txt)
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text

echo ""
echo "2️⃣ Checking if fix code is in container..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker exec automated-trading-platform-backend-aws-1 grep -c \"Check 2: Total open positions count\" /app/app/services/signal_monitor.py 2>/dev/null || echo \"0\""]' \
  --region "$REGION" \
  --output text --query "Command.CommandId" > /tmp/command_id2.txt

sleep 5
COMMAND_ID2=$(cat /tmp/command_id2.txt)
RESULT=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID2" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text | tail -1)

if [ "$RESULT" = "1" ]; then
  echo "✅ Fix code is present in container"
else
  echo "❌ Fix code not found - container may need restart or rebuild"
fi

echo ""
echo "3️⃣ Checking recent DOT order activity..."
aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker logs automated-trading-platform-backend-aws-1 2>&1 | grep -i \"DOT\" | grep -i \"order\\|signal\\|position\" | tail -15"]' \
  --region "$REGION" \
  --output text --query "Command.CommandId" > /tmp/command_id3.txt

sleep 5
COMMAND_ID3=$(cat /tmp/command_id3.txt)
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID3" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text

echo ""
echo "✅ Verification complete!"
