#!/bin/bash
# Deploy order cancellation notification changes to AWS

set -e

# Configuration
EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"

# Load SSH functions
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Try to determine which host to use
EC2_HOST=""
if ssh_cmd "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Using primary host: $EC2_HOST"
elif ssh_cmd "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Using alternative host: $EC2_HOST"
else
    echo "❌ Cannot connect to either host"
    echo "   Tried: $EC2_HOST_PRIMARY and $EC2_HOST_ALTERNATIVE"
    exit 1
fi

echo "========================================="
echo "Deploy Order Cancellation Notifications"
echo "========================================="
echo ""

# Sync backend code files
echo "📦 Syncing backend code files..."
rsync_cmd \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  backend/app/api/routes_orders.py \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/"

rsync_cmd \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  backend/app/services/exchange_sync.py \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/"

# Sync documentation
echo "📚 Syncing documentation..."
rsync_cmd docs/ORDER_CANCELLATION_NOTIFICATIONS.md \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/docs/"

rsync_cmd ORDER_CANCELLATION_NOTIFICATION_AUDIT.md \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/"

rsync_cmd CODE_REVIEW_NOTES.md \
  "$EC2_USER@$EC2_HOST:~/automated-trading-platform/"

# Restart backend service
echo "🔄 Restarting backend service..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY'
cd ~/automated-trading-platform
docker compose --profile aws restart backend-aws
echo "✅ Backend service restarted"
echo ""
echo "📋 Checking service status..."
sleep 3
docker compose --profile aws ps backend-aws
echo ""
echo "📜 Recent logs (last 30 lines)..."
docker compose --profile aws logs --tail=30 backend-aws
DEPLOY

echo ""
echo "✅ Deployment complete!"
echo ""
echo "💡 To monitor logs in real-time:"
echo "   ssh $EC2_USER@$EC2_HOST 'cd ~/automated-trading-platform && docker compose --profile aws logs -f backend-aws'"



