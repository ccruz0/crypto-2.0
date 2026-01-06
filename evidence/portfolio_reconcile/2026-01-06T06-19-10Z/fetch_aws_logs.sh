#!/bin/bash
# Fetch AWS backend logs via SSM
# Usage: ./fetch_aws_logs.sh

INSTANCE_ID="i-08726dc37133b2454"
OUTPUT_DIR="$(dirname "$0")"

echo "Fetching backend logs from AWS instance $INSTANCE_ID..."

aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || exit 1",
    "docker ps --format \"table {{.Names}}\t{{.Status}}\" | grep backend",
    "docker logs --tail 300 automated-trading-platform-backend-aws-1 2>&1 || docker logs --tail 300 backend-aws 2>&1 || echo \"Container not found\""
  ]' \
  --output text \
  --query "Command.CommandId" > /tmp/ssm_command_id.txt

COMMAND_ID=$(cat /tmp/ssm_command_id.txt)
echo "Command ID: $COMMAND_ID"
echo "Waiting for command to complete..."
sleep 5

aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --query "StandardOutputContent" \
  --output text > "$OUTPUT_DIR/backend_aws_logs_tail.txt" 2>&1

echo "Logs saved to: $OUTPUT_DIR/backend_aws_logs_tail.txt"
