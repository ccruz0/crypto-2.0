#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "Deploying position value calculation fix to AWS..."

# Sync the changed backend file
echo "Syncing expected_take_profit.py..."
rsync_cmd \
  backend/app/services/expected_take_profit.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/expected_take_profit.py

# Copy file into Docker container and restart
echo "Copying file into Docker container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform
docker cp backend/app/services/expected_take_profit.py automated-trading-platform_backend_1:/app/app/services/expected_take_profit.py
docker-compose restart backend
echo "Deployment complete! Backend restarted with position value fix."
DEPLOY

echo ""
echo "✅ Deployment complete!"
echo "The backend now calculates weighted average buy price from all purchase orders."

