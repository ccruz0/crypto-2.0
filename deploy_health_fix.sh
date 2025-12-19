#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Backend Health Fix feature to AWS..."

# Deploy backend
rsync_cmd backend/app/api/routes_control.py $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/

# Deploy frontend
rsync_cmd --exclude 'node_modules' --exclude '.next' frontend/src/app/api.ts frontend/src/app/page.tsx $EC2_USER@$EC2_HOST:~/automated-trading-platform/frontend/src/app/

# Update containers
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
if [ -n "$BACKEND_CONTAINER" ]; then
  docker cp backend/app/api/routes_control.py $BACKEND_CONTAINER:/app/app/api/routes_control.py
  docker-compose restart backend
fi
FRONTEND_CONTAINER=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -n "$FRONTEND_CONTAINER" ]; then
  docker cp frontend/src/app/api.ts $FRONTEND_CONTAINER:/app/src/app/api.ts
  docker cp frontend/src/app/page.tsx $FRONTEND_CONTAINER:/app/src/app/page.tsx
  docker-compose restart frontend
fi
echo "✅ Deployment complete!"
DEPLOY
