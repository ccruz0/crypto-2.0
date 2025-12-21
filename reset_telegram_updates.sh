#!/bin/bash
# Reset Telegram update state and check for pending updates

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "=== Resetting Telegram Update State ==="
echo ""

# Step 1: Delete webhook and drop pending updates
echo "Step 1: Deleting webhook and dropping pending updates..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "docker compose --profile aws exec backend-aws python3 -c \"import os; import requests; token=os.getenv(\\\"TELEGRAM_BOT_TOKEN\\\"); r=requests.post(f\\\"https://api.telegram.org/bot{token}/deleteWebhook\\\", json={\\\"drop_pending_updates\\\": True}, timeout=5); print(f\\\"Delete webhook: {r.json()}\\\")\""
  ]' \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting for command to complete..."
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION"

echo ""
echo "Step 2: Pulling latest code..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "git config --global --add safe.directory /home/ubuntu/automated-trading-platform",
    "git pull origin main"
  ]' \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION"

echo ""
echo "Step 3: Restarting backend service..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "docker compose --profile aws restart backend-aws"
  ]' \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION"

echo ""
echo "Step 4: Checking for pending updates (no offset)..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "sleep 5",
    "docker compose --profile aws exec backend-aws python3 -c \"import os; import requests; token=os.getenv(\\\"TELEGRAM_BOT_TOKEN\\\"); r=requests.get(f\\\"https://api.telegram.org/bot{token}/getUpdates?timeout=2\\\", timeout=5); data=r.json(); result=data.get(\\\"result\\\", []); print(f\\\"Pending updates: {len(result)}\\\"); [print(f\\\"  Update {u.get(\\\"update_id\\\")}: {u.get(\\\"message\\\", {}).get(\\\"text\\\", u.get(\\\"callback_query\\\", {}).get(\\\"data\\\", \\\"N/A\\\"))}\\\") for u in result[-10:]]\""
  ]' \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION"

echo ""
echo "=== Reset Complete ==="
echo "The backend service has been restarted with the new code."
echo "It will now check for pending updates without offset when no updates are received."
echo ""
echo "Please send a /start command to test."

