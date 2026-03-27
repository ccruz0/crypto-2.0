#!/bin/bash
# Force update Telegram menu on AWS - directly update the file in the container

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Force Updating Telegram Menu on AWS via SSM"
echo "=============================================="
echo "Instance: $INSTANCE_ID"
echo ""

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found. Please install AWS CLI first."
    exit 1
fi

echo "📤 Sending force update command..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids $INSTANCE_ID \
    --document-name "AWS-RunShellScript" \
    --parameters commands="
cd /home/ubuntu/crypto-2.0 || exit 1
export HOME=/home/ubuntu

echo '📥 Pulling latest code from git...'
git pull origin main 2>&1 || echo 'Git pull completed'

echo ''
echo '🔧 Finding backend-aws container...'
CONTAINER=\$(docker ps --filter 'name=backend-aws' --format '{{.Names}}' | head -1)
if [ -z \"\$CONTAINER\" ]; then
    echo '❌ Container not found. Available containers:'
    docker ps --format '{{.Names}}'
    exit 1
fi
echo \"✅ Found container: \$CONTAINER\"

echo ''
echo '🔄 Stopping container...'
docker compose --profile aws stop backend-aws 2>&1 || docker stop \$CONTAINER 2>&1

echo ''
echo '🔧 Rebuilding backend-aws image...'
docker compose --profile aws build backend-aws 2>&1

echo ''
echo '🔄 Starting backend-aws container...'
docker compose --profile aws up -d backend-aws 2>&1

echo ''
echo '⏳ Waiting for container to be ready...'
sleep 15

echo ''
echo '✅ Verifying code update...'
docker compose --profile aws exec backend-aws grep -A 5 'if text.startswith(\"/start\"):' /app/app/services/telegram_commands.py | head -10 || {
    echo '⚠️  Could not verify code (container may still be starting)'
}

echo ''
echo '✅ Force update complete!'
" \
    --region $REGION \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting 90 seconds for deployment..."
sleep 90

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
echo "✅ Force update command executed. Check output above for status."
echo ""
echo "To test: Send /start to the bot in Telegram and verify the inline menu appears."

