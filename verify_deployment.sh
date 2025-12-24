#!/bin/bash

echo "🔍 Verifying TP/SL Value fix deployment..."
echo ""

# Check source code on server
echo "1. Checking source code on server:"
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ubuntu/automated-trading-platform/frontend/src/app","grep -c \"TP Value\" page.tsx","grep -c \"SL Value\" page.tsx"]' \
  --region ap-southeast-1 \
  --query 'Command.CommandId' \
  --output text > /tmp/verify_cmd_id.txt 2>&1

COMMAND_ID=$(cat /tmp/verify_cmd_id.txt)
echo "   Command ID: $COMMAND_ID"
echo "   Waiting for result..."
sleep 8

RESULT=$(aws ssm get-command-invocation \
  --command-id $COMMAND_ID \
  --instance-id i-08726dc37133b2454 \
  --region ap-southeast-1 \
  --query 'StandardOutputContent' \
  --output text 2>&1)

echo "   Result: $RESULT"
echo ""

# Check container status
echo "2. Checking container status:"
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker ps --filter \"name=frontend-aws\" --format \"{{.Names}} {{.Status}}\""]' \
  --region ap-southeast-1 \
  --query 'Command.CommandId' \
  --output text > /tmp/verify_cmd_id2.txt 2>&1

COMMAND_ID2=$(cat /tmp/verify_cmd_id2.txt)
sleep 5

RESULT2=$(aws ssm get-command-invocation \
  --command-id $COMMAND_ID2 \
  --instance-id i-08726dc37133b2454 \
  --region ap-southeast-1 \
  --query 'StandardOutputContent' \
  --output text 2>&1)

echo "   $RESULT2"
echo ""
echo "✅ Verification complete!"
