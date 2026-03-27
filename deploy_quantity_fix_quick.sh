#!/bin/bash
set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
PROJECT_DIR="automated-trading-platform"

echo "🚀 Quick Deploy: Quantity Formatting Fix"
echo "=========================================="
echo ""

# Load SSH configuration
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "📦 Step 1: Syncing crypto_com_trade.py to AWS..."
rsync_cmd \
  -v \
  backend/app/services/brokers/crypto_com_trade.py \
  $EC2_USER@$EC2_HOST:~/$PROJECT_DIR/backend/app/services/brokers/

echo ""
echo "🔄 Step 2: Restarting backend container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/crypto-2.0

# Find backend container
CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker compose ps -q backend 2>/dev/null || echo "")

if [ -z "$CONTAINER" ]; then
    echo "⚠️  Backend container not found, trying to restart all services..."
    docker compose --profile aws restart backend-aws 2>/dev/null || docker compose restart backend 2>/dev/null || {
        echo "❌ Could not restart. Trying full restart..."
        docker compose --profile aws down && docker compose --profile aws up -d
    }
else
    echo "✅ Found container: $CONTAINER"
    echo "📋 Copying file into container..."
    docker cp backend/app/services/brokers/crypto_com_trade.py $CONTAINER:/app/app/services/brokers/crypto_com_trade.py
    
    echo "🔄 Restarting container..."
    docker restart $CONTAINER
    
    echo "⏳ Waiting for container to be healthy..."
    sleep 5
    
    echo "📊 Container status:"
    docker ps --filter id=$CONTAINER --format "table {{.ID}}\t{{.Status}}\t{{.Names}}"
    
    echo ""
    echo "📋 Recent logs:"
    docker logs --tail=20 $CONTAINER
fi

echo ""
echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "🎉 Quick deployment finished!"
