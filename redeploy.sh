#!/bin/bash
# Full redeploy to EC2: pull code, rebuild backend + frontend, restart services and nginx.
# Run from your machine (requires AWS CLI and SSM access). Push your changes to origin main first.
set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"
REPO_DIR="/home/ubuntu/automated-trading-platform"

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "🚀 Redeploying backend + frontend on EC2"
echo "========================================"
echo "   Instance: $INSTANCE_ID"
echo "   Repo:     $REPO_DIR"
echo ""
echo "📤 Sending redeploy command (pull, build, up, nginx restart)..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["set -e","cd /home/ubuntu/automated-trading-platform","git -c safe.directory=/home/ubuntu/automated-trading-platform pull origin main || true","docker compose --profile aws build --no-cache backend-aws frontend-aws","docker compose --profile aws up -d","sleep 5","sudo systemctl restart nginx || true","docker compose --profile aws ps","echo Done."]' \
    --region "$REGION" \
    --timeout-seconds 600 \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [[ -z "$COMMAND_ID" ]]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 120s for build and restart..."
sleep 120

echo ""
echo "📊 Output:"
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1 | head -80

echo ""
echo "🎉 Redeploy requested. Verify: curl -s https://dashboard.hilovivo.com/api/ping_fast"
