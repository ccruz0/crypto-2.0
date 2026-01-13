#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "Deploying contradictory alerts fix to AWS..."

# Sync the changed backend file
echo "Syncing backend file..."
rsync_cmd \
  backend/app/services/exchange_sync.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/exchange_sync.py

# Copy file into Docker container and restart
echo "Copying file into Docker container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform
docker cp backend/app/services/exchange_sync.py automated-trading-platform_backend_1:/app/app/services/exchange_sync.py
docker-compose restart backend
echo "✅ Deployment complete! Backend restarted with contradictory alerts fix"
echo ""
echo "Checking backend logs..."
sleep 3
docker-compose logs --tail=30 backend
DEPLOY







