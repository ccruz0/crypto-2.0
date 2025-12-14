#!/bin/bash

# Combined deployment script for open orders fix (backend + frontend)
# Tries both AWS servers

set -e

EC2_HOST_1="54.254.150.31"
EC2_HOST_2="175.41.189.249"
EC2_USER="ubuntu"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Open Orders Fix (Backend + Frontend)"
echo "=================================================="
echo ""

# Function to test SSH connection
test_ssh() {
    local host=$1
    ssh_cmd "$EC2_USER@$host" "echo 'SSH OK'" 2>/dev/null && return 0 || return 1
}

# Try to find which server is accessible
EC2_HOST=""
if test_ssh "$EC2_HOST_1"; then
    EC2_HOST="$EC2_HOST_1"
    echo "✅ Connected to server 1: $EC2_HOST"
elif test_ssh "$EC2_HOST_2"; then
    EC2_HOST="$EC2_HOST_2"
    echo "✅ Connected to server 2: $EC2_HOST"
else
    echo "❌ Cannot connect to either server"
    echo "   Tried: $EC2_HOST_1 and $EC2_HOST_2"
    exit 1
fi

echo ""
echo "📦 Step 1: Syncing backend file..."
rsync_cmd \
  backend/app/api/routes_dashboard.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/

echo ""
echo "📦 Step 2: Syncing frontend file..."
rsync_cmd \
  --exclude='node_modules' \
  --exclude='.next' \
  frontend/src/app/page.tsx \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/frontend/src/app/

echo ""
echo "🐳 Step 3: Copying files into Docker containers and restarting..."
ssh_cmd $EC2_USER@$EC2_HOST bash << 'DEPLOY'
cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Find containers
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
FRONTEND_CONTAINER=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)

if [ -z "$BACKEND_CONTAINER" ]; then
  echo "⚠️  Backend container not found, trying docker-compose..."
  BACKEND_CONTAINER=$(docker-compose ps backend --format json 2>/dev/null | jq -r '.[0].Name' 2>/dev/null || echo "")
fi

if [ -z "$FRONTEND_CONTAINER" ]; then
  echo "⚠️  Frontend container not found, trying docker-compose..."
  FRONTEND_CONTAINER=$(docker-compose ps frontend --format json 2>/dev/null | jq -r '.[0].Name' 2>/dev/null || echo "")
fi

# Deploy backend
if [ -n "$BACKEND_CONTAINER" ]; then
  echo "📋 Found backend container: $BACKEND_CONTAINER"
  docker cp backend/app/api/routes_dashboard.py $BACKEND_CONTAINER:/app/app/api/routes_dashboard.py
  echo "✅ Backend file copied"
else
  echo "❌ Backend container not found"
  docker ps
fi

# Deploy frontend
if [ -n "$FRONTEND_CONTAINER" ]; then
  echo "📋 Found frontend container: $FRONTEND_CONTAINER"
  docker cp frontend/src/app/page.tsx $FRONTEND_CONTAINER:/app/src/app/page.tsx
  echo "✅ Frontend file copied"
else
  echo "❌ Frontend container not found"
  docker ps
fi

# Restart services
echo ""
echo "🔄 Restarting services..."
if [ -n "$BACKEND_CONTAINER" ] && [ -n "$FRONTEND_CONTAINER" ]; then
  docker-compose restart backend frontend 2>/dev/null || {
    echo "Trying individual restarts..."
    [ -n "$BACKEND_CONTAINER" ] && docker restart $BACKEND_CONTAINER
    [ -n "$FRONTEND_CONTAINER" ] && docker restart $FRONTEND_CONTAINER
  }
else
  echo "⚠️  Some containers not found, restarting individually..."
  [ -n "$BACKEND_CONTAINER" ] && docker restart $BACKEND_CONTAINER
  [ -n "$FRONTEND_CONTAINER" ] && docker restart $FRONTEND_CONTAINER
fi

echo ""
echo "⏳ Waiting 5 seconds for services to restart..."
sleep 5

# Health checks
echo ""
echo "🏥 Checking service health..."
if [ -n "$BACKEND_CONTAINER" ]; then
  if curl -f --connect-timeout 5 http://localhost:8000/api/health > /dev/null 2>&1; then
    echo "✅ Backend is healthy"
  else
    echo "⚠️  Backend health check failed - check logs: docker logs $BACKEND_CONTAINER"
  fi
fi

if [ -n "$FRONTEND_CONTAINER" ]; then
  if curl -f --connect-timeout 5 http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ Frontend is responding"
  else
    echo "⚠️  Frontend health check failed - check logs: docker logs $FRONTEND_CONTAINER"
  fi
fi

echo ""
echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "=================================================="
echo "✅ Deployment Summary"
echo "=================================================="
echo "Backend: Fixed TP orders counting (only active orders)"
echo "Frontend: Enhanced tooltip showing TP orders on hover"
echo ""
echo "Changes:"
echo "  • Only counts TP orders with status: NEW, ACTIVE, PARTIALLY_FILLED"
echo "  • Tooltip shows formatted list of active TP orders"
echo "  • This fixes inflated counts (e.g., ALGO showing 36 instead of actual)"
echo ""

