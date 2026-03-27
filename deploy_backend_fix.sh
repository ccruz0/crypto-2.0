#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "Deploying backend fixes to AWS..."

# Sync only the changed backend files
echo "Syncing backend files..."
rsync_cmd \
  backend/app/services/brokers/crypto_com_trade.py \
  backend/app/api/routes_account.py \
  $EC2_USER@$EC2_HOST:~/crypto-2.0/backend/app/

# Copy files into Docker container and restart
echo "Copying files into Docker container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/crypto-2.0
docker cp backend/app/services/brokers/crypto_com_trade.py automated-trading-platform_backend_1:/app/app/services/brokers/crypto_com_trade.py
docker cp backend/app/api/routes_account.py automated-trading-platform_backend_1:/app/app/api/routes_account.py
docker-compose restart backend
echo "Deployment complete!"
DEPLOY
