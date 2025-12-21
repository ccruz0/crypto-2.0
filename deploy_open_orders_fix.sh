#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying open orders count fix to AWS..."
echo ""

# Sync the changed backend file
echo "📦 Syncing backend file..."
rsync_cmd \
  backend/app/api/routes_dashboard.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/

# Copy file into Docker container and restart
echo "🐳 Copying file into Docker container and restarting..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find the backend container name
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "❌ Backend container not found. Trying alternative method..."
  BACKEND_CONTAINER=$(docker-compose ps backend --format json | jq -r '.[0].Name' 2>/dev/null || echo "")
fi

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "❌ Could not find backend container. Listing all containers:"
  docker ps
  exit 1
fi

echo "📋 Found backend container: $BACKEND_CONTAINER"

# Copy file into container
docker cp backend/app/api/routes_dashboard.py $BACKEND_CONTAINER:/app/app/api/routes_dashboard.py

# Restart backend
echo "🔄 Restarting backend container..."
docker-compose restart backend || docker restart $BACKEND_CONTAINER

echo "✅ Deployment complete!"
echo ""
echo "Waiting 5 seconds for backend to restart..."
sleep 5

# Check if backend is healthy
echo "🏥 Checking backend health..."
if curl -f --connect-timeout 5 http://localhost:8000/api/health > /dev/null 2>&1; then
  echo "✅ Backend is healthy"
else
  echo "⚠️  Backend health check failed - check logs with: docker logs $BACKEND_CONTAINER"
fi
DEPLOY

echo ""
echo "✅ Deployment script complete!"
echo ""
echo "The fix ensures only active TP orders (NEW, ACTIVE, PARTIALLY_FILLED) are counted."
echo "This should resolve the inflated open orders count (e.g., ALGO showing 36 instead of actual active orders)."






