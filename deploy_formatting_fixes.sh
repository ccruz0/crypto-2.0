#!/bin/bash
# Deploy formatting fixes to AWS via SSM
# This deploys the formatting compliance fixes

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/scripts/ensure_repo_root.sh"
ensure_repo_root

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Deploying Formatting Fixes via AWS SSM"
echo "========================================="
echo ""
echo "This will deploy:"
echo "  - Formatting compliance fixes (normalize_price helper)"
echo "  - Correct rounding directions"
echo "  - Trailing zero preservation"
echo "  - Decimal usage (no binary floats)"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "📤 Sending deployment command..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
      "cd /home/ubuntu/automated-trading-platform",
      "echo \"📥 Pulling latest code...\"",
      "git pull origin main || echo \"⚠️ Git pull failed, continuing...\"",
      "echo \"🔨 Rebuilding backend-aws container...\"",
      "docker compose --profile aws build backend-aws",
      "echo \"🔄 Restarting backend-aws container...\"",
      "docker compose --profile aws restart backend-aws",
      "echo \"⏳ Waiting for container to be healthy...\"",
      "sleep 15",
      "echo \"📊 Container status:\"",
      "docker compose --profile aws ps backend-aws",
      "echo \"\"",
      "echo \"🔍 Checking backend health...\"",
      "curl -sS -m 10 http://127.0.0.1:8002/health || echo \"⚠️ Health check failed\"",
      "echo \"\"",
      "echo \"✅ Backend deployment complete!\""
    ]' \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 60 seconds for deployment..."
sleep 60

echo ""
echo "📊 Deployment Result:"
aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | tail -50

echo ""
echo "🎉 Deployment initiated!"
echo ""
echo "To check status again, run:"
echo "  aws ssm get-command-invocation \\"
echo "    --command-id $COMMAND_ID \\"
echo "    --instance-id $INSTANCE_ID \\"
echo "    --region $REGION"
