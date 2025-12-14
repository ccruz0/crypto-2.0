#!/bin/bash

REMOTE_HOST="hilovivo-aws"
REMOTE_USER="ubuntu"
PROJECT_DIR="~/automated-trading-platform"

echo "Deploying stale orders fix to AWS..."

# Check SSH connection
echo "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ Cannot connect to $REMOTE_HOST"
    echo "Make sure your SSH config has 'hilovivo-aws' alias configured"
    exit 1
fi

# Sync the changed backend files
echo "Syncing backend files..."
rsync -avz --progress \
  backend/app/api/routes_orders.py \
  backend/app/services/exchange_sync.py \
  backend/scripts/verify_and_cleanup_stale_orders.py \
  "$REMOTE_HOST:$PROJECT_DIR/backend/"

# Copy files into Docker container and restart
echo "Copying files into Docker container and restarting..."
ssh "$REMOTE_HOST" << 'DEPLOY'
cd ~/automated-trading-platform

# Find the backend container name
BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'backend|backend-aws' | head -1)

if [ -z "$BACKEND_CONTAINER" ]; then
    echo "❌ Backend container not found!"
    exit 1
fi

echo "Using container: $BACKEND_CONTAINER"

# Copy files into container
docker cp backend/app/api/routes_orders.py $BACKEND_CONTAINER:/app/app/api/routes_orders.py
docker cp backend/app/services/exchange_sync.py $BACKEND_CONTAINER:/app/app/services/exchange_sync.py
docker cp backend/scripts/verify_and_cleanup_stale_orders.py $BACKEND_CONTAINER:/app/scripts/verify_and_cleanup_stale_orders.py

# Restart backend
echo "Restarting backend container..."
docker compose --profile aws restart backend-aws 2>/dev/null || docker compose restart backend 2>/dev/null || docker restart $BACKEND_CONTAINER

echo "✅ Stale orders fix deployed!"
echo "📋 New API endpoint available: POST /api/orders/verify-stale"
echo "🔧 Sync will now properly detect and cleanup stale orders automatically"
DEPLOY

echo ""
echo "✅ Deployment complete!"

