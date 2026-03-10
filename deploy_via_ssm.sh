#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/ensure_repo_root.sh"
ensure_repo_root

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying via AWS Session Manager (SSM)"
echo "==========================================="
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deployment command..."

# Use absolute path and simpler commands
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["cd /home/ubuntu/automated-trading-platform","git -c safe.directory=/home/ubuntu/automated-trading-platform pull origin main || true","CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo \"\")","if [ -n \"$CONTAINER\" ]; then docker restart $CONTAINER; else docker compose --profile aws up -d --build; fi","sleep 10","docker compose --profile aws ps"]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 40 seconds for execution..."
sleep 40

echo ""
echo "📊 Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | head -50

echo ""
echo "🎉 Deployment initiated!"
