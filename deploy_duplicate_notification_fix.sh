#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying duplicate notification fix to AWS..."
echo "=================================================="

# Sync only the changed backend file
echo "📦 Syncing exchange_sync.py..."
rsync_cmd \
  backend/app/services/exchange_sync.py \
  $EC2_USER@$EC2_HOST:~/crypto-2.0/backend/app/services/

# Copy file into Docker container and restart
echo "🔧 Copying file into Docker container and restarting..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/crypto-2.0
docker cp backend/app/services/exchange_sync.py automated-trading-platform_backend-aws_1:/app/app/services/exchange_sync.py 2>/dev/null || \
docker cp backend/app/services/exchange_sync.py automated-trading-platform_backend_1:/app/app/services/exchange_sync.py
docker-compose restart backend-aws 2>/dev/null || docker-compose restart backend
echo "✅ Deployment complete!"
echo ""
echo "The fix will prevent duplicate ORDER EXECUTED notifications."
echo "Each executed order will now only send one Telegram notification."
DEPLOY

echo ""
echo "✅ Fix deployed! Monitor logs to verify notifications are no longer repeating."


