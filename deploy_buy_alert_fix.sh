#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying BUY alert fix to AWS..."
echo ""
echo "Fix: Added missing throttling check for BUY alerts in signal_monitor.py"
echo "This fixes the issue where TRX_USDT and other symbols weren't sending buy alerts"
echo ""

# Sync only the changed backend file
echo "📦 Syncing signal_monitor.py..."
rsync_cmd \
  backend/app/services/signal_monitor.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/

# Copy file into Docker container and restart
echo "🐳 Copying file into Docker container and restarting backend..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find the backend container name
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "❌ Error: Backend container not found"
  exit 1
fi

echo "📋 Found backend container: $BACKEND_CONTAINER"

# Copy the file into the container
docker cp backend/app/services/signal_monitor.py $BACKEND_CONTAINER:/app/app/services/signal_monitor.py

# Restart the backend container
echo "🔄 Restarting backend container..."
docker-compose restart backend || docker restart $BACKEND_CONTAINER

# Wait a moment for the service to restart
sleep 5

# Check if backend is running
if docker ps --filter "name=backend" --format "{{.Status}}" | grep -q "Up"; then
  echo "✅ Backend restarted successfully"
else
  echo "⚠️  Warning: Backend container status unclear"
fi

echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "✅ Fix deployed successfully!"
echo ""
echo "The BUY alert throttling check has been added to signal_monitor.py"
echo "TRX_USDT and other symbols should now properly send buy alerts when conditions are met."







