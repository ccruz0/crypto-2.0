#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying quantity formatting fix to AWS..."

# Sync the changed file
echo "📦 Syncing crypto_com_trade.py..."
rsync_cmd \
  backend/app/services/brokers/crypto_com_trade.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/brokers/

# Copy file into Docker container and restart
echo "🔄 Restarting backend service..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform
CONTAINER_NAME=$(docker-compose ps -q backend)
if [ -n "$CONTAINER_NAME" ]; then
    docker cp backend/app/services/brokers/crypto_com_trade.py $CONTAINER_NAME:/app/app/services/brokers/crypto_com_trade.py
    docker-compose restart backend
    echo "✅ Backend restarted successfully"
    sleep 5
    docker-compose logs --tail=20 backend
else
    echo "⚠️  Backend container not found, trying docker compose..."
    docker compose restart backend || echo "⚠️  Could not restart, may need manual restart"
fi
DEPLOY

echo ""
echo "✅ Deployment complete!"
