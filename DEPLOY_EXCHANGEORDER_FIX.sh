#!/bin/bash
# Deploy ExchangeOrder scope fix to AWS

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🔧 Deploying ExchangeOrder Scope Fix"
echo "====================================="
echo ""

# Verify AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📤 Copying fixed file to AWS..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "echo \"Checking if file needs update...\"",
    "grep -n \"from app.models.exchange_order import ExchangeOrder, OrderStatusEnum\" backend/app/services/signal_monitor.py | grep -v \"^16:\" | wc -l",
    "echo \"File checked\""
  ]' \
  --output text \
  --query "Command.CommandId" 2>/dev/null)

if [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command"
    exit 1
fi

echo "⚠️  Note: This fix requires git commit/push and deployment"
echo ""
echo "The fix removes redundant local imports of ExchangeOrder that cause scope errors."
echo "To deploy:"
echo "1. Commit the change: git add backend/app/services/signal_monitor.py && git commit -m 'Fix: Remove redundant ExchangeOrder imports'"
echo "2. Push: git push origin main"
echo "3. Pull on AWS and restart backend"
