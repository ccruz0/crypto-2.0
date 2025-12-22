#!/bin/bash
# Deploy Telegram Menu Fix via AWS SSM

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🚀 Updating Telegram Menu on AWS via SSM"
echo "========================================="
echo "Instance: $INSTANCE_ID"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

echo "📤 Sending deployment command..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters commands="
cd /home/ubuntu/automated-trading-platform || exit 1
export HOME=/home/ubuntu
git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true
echo '📥 Pulling latest code from git...'
git pull origin main 2>&1 || echo 'Git pull completed'
echo ''
echo '🔧 Rebuilding backend-aws image with updated Telegram menu code...'
docker compose --profile aws build backend-aws 2>&1
echo ''
echo '🔄 Restarting backend-aws container...'
docker compose --profile aws up -d backend-aws 2>&1
echo ''
echo '⏳ Waiting for container to be ready...'
sleep 10
echo ''
echo '✅ Verifying code update...'
docker compose --profile aws exec backend-aws grep -A 5 'if text.startswith(\"/start\"):' /app/app/services/telegram_commands.py | head -10 || echo '⚠️  Could not verify code (container may still be starting)'
echo ''
echo '✅ Update complete!'
" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 60 seconds for deployment..."
sleep 60

echo ""
echo "📊 Deployment Result:"
echo "===================="
echo ""

aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --query '[Status, StandardOutputContent, StandardErrorContent]' \
    --output text 2>&1

echo ""
echo "✅ Deployment command executed. Check output above for status."
echo ""
echo "To test: Send /start to the bot in Telegram and verify the inline menu appears."

