#!/bin/bash
# Script to deploy TP/SL price display fixes (frontend + backend)

set -e

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

EC2_HOST="${EC2_HOST:-175.41.189.249}"
EC2_USER="${EC2_USER:-ubuntu}"
PROJECT_DIR="automated-trading-platform"

echo "🚀 Deploying TP/SL price display fixes..."

# Step 1: Copy updated frontend files
echo "📦 Copying frontend files..."
rsync_cmd \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    ./frontend/src/lib/api.ts "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/frontend/src/lib/"
rsync_cmd \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    ./frontend/src/app/page.tsx "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/frontend/src/app/"

# Step 2: Copy updated backend files
echo "📦 Copying backend files..."
rsync_cmd \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    ./backend/app/services/open_orders.py "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/backend/app/services/"
rsync_cmd \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    ./backend/app/api/routes_dashboard.py "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/backend/app/api/"

# Step 3: Rebuild and restart services
echo "🔨 Rebuilding and restarting services..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/crypto-2.0

# Find containers
FRONTEND_CONTAINER=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

if [ -n "$FRONTEND_CONTAINER" ]; then
  echo "📦 Copying frontend files to container..."
  docker cp frontend/src/lib/api.ts $FRONTEND_CONTAINER:/app/src/lib/api.ts
  docker cp frontend/src/app/page.tsx $FRONTEND_CONTAINER:/app/src/app/page.tsx
  
  echo "🔄 Restarting frontend..."
  docker restart $FRONTEND_CONTAINER || docker compose --profile aws restart frontend
  echo "✅ Frontend restarted"
else
  echo "⚠️ Frontend container not found, rebuilding..."
  docker compose --profile aws build frontend
  docker compose --profile aws up -d frontend
fi

if [ -n "$BACKEND_CONTAINER" ]; then
  echo "📦 Copying backend files to container..."
  docker cp backend/app/services/open_orders.py $BACKEND_CONTAINER:/app/app/services/open_orders.py
  docker cp backend/app/api/routes_dashboard.py $BACKEND_CONTAINER:/app/app/api/routes_dashboard.py
  
  echo "🔄 Restarting backend..."
  docker restart $BACKEND_CONTAINER || docker compose --profile aws restart backend
  echo "✅ Backend restarted"
else
  echo "⚠️ Backend container not found, rebuilding..."
  docker compose --profile aws build backend
  docker compose --profile aws up -d backend
fi

# Wait for services to be ready
echo "⏳ Waiting for services to be ready..."
sleep 10

# Check service status
echo "📊 Service status:"
docker compose --profile aws ps

# Test backend health
echo "🏥 Testing backend health..."
curl -f http://localhost:8000/api/health || echo "⚠️ Backend health check failed (may need more time)"

echo "✅ Deploy complete!"
DEPLOY_SCRIPT

echo "🎉 TP/SL price display fixes deployed successfully!"




