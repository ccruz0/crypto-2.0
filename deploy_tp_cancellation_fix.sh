#!/bin/bash
set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying TP Cancellation Fix to AWS..."
echo "=========================================="
echo ""

# Sync the fixed file
echo "📦 Syncing backend/app/services/exchange_sync.py..."
rsync_cmd \
  backend/app/services/exchange_sync.py \
  $EC2_USER@$EC2_HOST:~/crypto-2.0/backend/app/services/exchange_sync.py

echo ""
echo "🔄 Restarting backend container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/crypto-2.0

# Find backend container name
CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker compose ps -q backend 2>/dev/null || echo "")

if [ -n "$CONTAINER" ]; then
    echo "📋 Found container: $CONTAINER"
    echo "📁 Copying file to container..."
    docker cp backend/app/services/exchange_sync.py $CONTAINER:/app/app/services/exchange_sync.py
    echo "🔄 Restarting container..."
    docker restart $CONTAINER
    echo "⏳ Waiting for container to start..."
    sleep 5
    echo "✅ Container restarted"
else
    echo "⚠️  No container found, rebuilding..."
    docker compose --profile aws up -d --build backend
    sleep 10
fi

echo ""
echo "📊 Container status:"
docker compose --profile aws ps backend 2>/dev/null || docker compose ps backend 2>/dev/null || echo "Container not found in compose"

echo ""
echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "🎉 TP Cancellation Fix deployed successfully!"
echo ""
echo "📝 Changes deployed:"
echo "   - Fixed _cancel_oco_sibling() to include OPEN status"
echo "   - Enhanced diagnostic logging in cancellation functions"
echo ""
echo "💡 Monitor logs for cancellation attempts to verify the fix is working"







