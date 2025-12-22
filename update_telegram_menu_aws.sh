#!/bin/bash
# Script to update Telegram menu on AWS by rebuilding backend-aws container

set -e

# Load SSH configuration
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Try to determine AWS host
EC2_HOST_PRIMARY="175.41.189.249"
EC2_HOST_ALTERNATIVE="54.254.150.31"
EC2_USER="ubuntu"
PROJECT_DIR="automated-trading-platform"

# Try to connect to primary host first
EC2_HOST=""
if ssh_cmd -o ConnectTimeout=5 "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Using primary host: $EC2_HOST"
elif ssh_cmd -o ConnectTimeout=5 "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Using alternative host: $EC2_HOST"
else
    echo "❌ Cannot connect to either host"
    echo "   Tried: $EC2_HOST_PRIMARY and $EC2_HOST_ALTERNATIVE"
    exit 1
fi

echo "=========================================="
echo "Updating Telegram Menu on AWS"
echo "=========================================="
echo "Host: $EC2_HOST"
echo ""

# Execute commands on AWS
ssh_cmd "$EC2_USER@$EC2_HOST" << 'REMOTE_SCRIPT'
set -e

cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform || {
    echo "❌ Cannot find project directory"
    exit 1
}

echo "📥 Pulling latest code from git..."
git pull origin main || {
    echo "⚠️  Git pull failed, continuing with existing code..."
}

echo ""
echo "🔧 Rebuilding backend-aws image with updated Telegram menu code..."
docker compose --profile aws build backend-aws

echo ""
echo "🔄 Restarting backend-aws container..."
docker compose --profile aws up -d backend-aws

echo ""
echo "⏳ Waiting for container to be ready..."
sleep 10

echo ""
echo "✅ Verifying code update..."
docker compose --profile aws exec backend-aws grep -A 5 "if text.startswith(\"/start\"):" /app/app/services/telegram_commands.py | head -10 || {
    echo "⚠️  Could not verify code (container may still be starting)"
}

echo ""
echo "✅ Done! The Telegram menu should now show the inline buttons menu."
echo "   Test by sending /start to the bot in Telegram."

REMOTE_SCRIPT

echo ""
echo "✅ Update complete on AWS!"
echo ""
echo "To monitor logs:"
echo "  ssh $EC2_USER@$EC2_HOST 'cd ~/automated-trading-platform && docker compose --profile aws logs -f backend-aws | grep -i TG'"

