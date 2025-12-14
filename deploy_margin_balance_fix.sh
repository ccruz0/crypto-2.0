#!/bin/bash

EC2_HOST="175.41.189.249"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying margin balance fix to AWS..."

# Sync only the changed backend file
echo "📦 Syncing signal_monitor.py..."
rsync_cmd \
  backend/app/services/signal_monitor.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/

# Copy file into Docker container and restart
echo "🐳 Copying file into Docker container and restarting..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find the backend container name (it might vary)
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "❌ Backend container not found. Trying alternative method..."
  BACKEND_CONTAINER=$(docker-compose ps backend | tail -1 | awk '{print $1}')
fi

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "❌ Could not find backend container. Available containers:"
  docker ps --format "{{.Names}}"
  exit 1
fi

echo "✅ Found backend container: $BACKEND_CONTAINER"

# Copy the file
docker cp backend/app/services/signal_monitor.py $BACKEND_CONTAINER:/app/app/services/signal_monitor.py

# Restart the backend
echo "🔄 Restarting backend..."
docker-compose restart backend || docker restart $BACKEND_CONTAINER

echo "⏳ Waiting for backend to be ready..."
sleep 5

# Check if backend is running
if docker ps | grep -q "$BACKEND_CONTAINER"; then
  echo "✅ Backend restarted successfully!"
else
  echo "⚠️  Warning: Backend container status unclear"
fi

echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "✅ Fix deployed! The system will now check margin settings before blocking orders."
