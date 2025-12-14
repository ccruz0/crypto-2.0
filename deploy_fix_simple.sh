#!/bin/bash

EC2_HOST="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Open Orders Fix"
echo "============================="
echo ""

# Step 1: Sync files
echo "📦 Syncing files..."
rsync_cmd backend/app/api/routes_dashboard.py $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/ 2>&1 | grep -v "error:" | grep -v "warning:" || true
rsync_cmd frontend/src/app/page.tsx $EC2_USER@$EC2_HOST:~/automated-trading-platform/frontend/src/app/ 2>&1 | grep -v "error:" | grep -v "warning:" || true

echo ""
echo "🐳 Deploying to Docker containers..."

# Step 2: Deploy via SSH
ssh_cmd $EC2_USER@$EC2_HOST 'bash -s' << 'REMOTE_SCRIPT'
cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Find containers
BACKEND=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
FRONTEND=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)

echo "Backend container: ${BACKEND:-NOT FOUND}"
echo "Frontend container: ${FRONTEND:-NOT FOUND}"

# Copy backend
if [ -n "$BACKEND" ]; then
  docker cp backend/app/api/routes_dashboard.py $BACKEND:/app/app/api/routes_dashboard.py
  echo "✅ Backend file copied"
fi

# Copy frontend  
if [ -n "$FRONTEND" ]; then
  docker cp frontend/src/app/page.tsx $FRONTEND:/app/src/app/page.tsx
  echo "✅ Frontend file copied"
fi

# Restart
if [ -n "$BACKEND" ] || [ -n "$FRONTEND" ]; then
  docker-compose restart backend frontend 2>/dev/null || {
    [ -n "$BACKEND" ] && docker restart $BACKEND
    [ -n "$FRONTEND" ] && docker restart $FRONTEND
  }
  echo "✅ Services restarted"
  sleep 5
  curl -f http://localhost:8000/api/health >/dev/null 2>&1 && echo "✅ Backend healthy" || echo "⚠️  Backend check failed"
fi

echo "✅ Deployment complete!"
REMOTE_SCRIPT

echo ""
echo "✅ All done!"

