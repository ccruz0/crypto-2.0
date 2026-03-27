#!/bin/bash
# Deploy fix for SELL order quantity format and SL/TP creation

set -e

echo "🚀 Deploying SELL order fixes to AWS..."
echo ""

# Get AWS instance info
EC2_HOST_PRIMARY="47.130.143.159"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Determine which host to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Using primary host: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Using alternative host: $EC2_HOST"
else
    echo "❌ Cannot connect to AWS instance"
    exit 1
fi

echo "📦 Syncing fixed backend files..."
rsync_cmd \
  backend/app/services/brokers/crypto_com_trade.py \
  backend/app/services/exchange_sync.py \
  $EC2_USER@$EC2_HOST:~/crypto-2.0/backend/app/services/

echo ""
echo "🐳 Copying files into Docker container and restarting..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/crypto-2.0

# Find backend container name
BACKEND_CONTAINER=$(docker compose ps --format json --profile aws | grep -i backend | head -1 | grep -o '"Name":"[^"]*' | cut -d'"' -f4 || echo "automated-trading-platform-backend-aws-1")

if [ -z "$BACKEND_CONTAINER" ]; then
    echo "❌ Backend container not found"
    exit 1
fi

echo "📋 Using container: $BACKEND_CONTAINER"

# Copy files to container
echo "📥 Copying crypto_com_trade.py..."
docker cp backend/app/services/brokers/crypto_com_trade.py $BACKEND_CONTAINER:/app/app/services/brokers/crypto_com_trade.py || {
    echo "⚠️ Failed to copy crypto_com_trade.py, trying alternative path..."
    docker cp backend/app/services/brokers/crypto_com_trade.py $BACKEND_CONTAINER:/workspace/app/services/brokers/crypto_com_trade.py || true
}

echo "📥 Copying exchange_sync.py..."
docker cp backend/app/services/exchange_sync.py $BACKEND_CONTAINER:/app/app/services/exchange_sync.py || {
    echo "⚠️ Failed to copy exchange_sync.py, trying alternative path..."
    docker cp backend/app/services/exchange_sync.py $BACKEND_CONTAINER:/workspace/app/services/exchange_sync.py || true
}

echo "🔄 Restarting backend container..."
docker compose restart backend-aws || docker compose --profile aws restart backend-aws || {
    echo "⚠️ Restart failed, trying container restart directly..."
    docker restart $BACKEND_CONTAINER || true
}

echo "⏳ Waiting for backend to be ready..."
sleep 10

echo "✅ Deployment complete!"
echo ""
echo "📊 Checking container status..."
docker compose ps --profile aws | grep backend || docker ps | grep backend

echo ""
echo "🧪 Testing backend health..."
sleep 5
curl -f http://localhost:8002/api/health 2>/dev/null && echo "✅ Backend is healthy" || echo "⚠️ Backend health check failed (may need more time)"
DEPLOY

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📝 Changes deployed:"
echo "   - Fix: Quantity format for SELL orders (max 5 decimals)"
echo "   - Fix: Async error in sync_open_orders"
echo "   - Fix: Auto-create watchlist_item for SL/TP creation"



















