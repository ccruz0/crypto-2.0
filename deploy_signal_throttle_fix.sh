#!/bin/bash

# Try multiple server options
EC2_HOST_1="54.254.150.31"
EC2_HOST_2="175.41.189.249"
EC2_HOST_SSH="hilovivo-aws"
EC2_USER="ubuntu"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying signal throttle fix to AWS..."

# Determine which server to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_HOST_SSH" "echo 'Connected'" > /dev/null 2>&1; then
  EC2_HOST="$EC2_HOST_SSH"
  echo "✅ Using SSH host alias: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_2" "echo 'Connected'" > /dev/null 2>&1; then
  EC2_HOST="$EC2_USER@$EC2_HOST_2"
  echo "✅ Using server: $EC2_HOST_2"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_1" "echo 'Connected'" > /dev/null 2>&1; then
  EC2_HOST="$EC2_USER@$EC2_HOST_1"
  echo "✅ Using server: $EC2_HOST_1"
else
  echo "❌ Cannot connect to any AWS server"
  echo "   Tried: $EC2_HOST_SSH, $EC2_HOST_2, $EC2_HOST_1"
  exit 1
fi

# Sync the changed backend files
echo "📦 Syncing backend files..."
if [[ "$EC2_HOST" == "hilovivo-aws" ]]; then
  rsync -avz -e "ssh -o StrictHostKeyChecking=no" \
    backend/app/api/signal_monitor.py \
    backend/app/services/signal_throttle.py \
    $EC2_HOST:~/automated-trading-platform/backend/app/
else
  rsync_cmd \
    backend/app/api/signal_monitor.py \
    backend/app/services/signal_throttle.py \
    $EC2_HOST:~/automated-trading-platform/backend/app/
fi

# Copy files into Docker container and restart
echo "🐳 Copying files into Docker container and restarting..."
if [[ "$EC2_HOST" == "hilovivo-aws" ]]; then
  ssh -o StrictHostKeyChecking=no $EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find the correct backend container name (try different patterns)
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
if [ -z "$BACKEND_CONTAINER" ]; then
  BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
fi
if [ -z "$BACKEND_CONTAINER" ]; then
  BACKEND_CONTAINER=$(docker ps | grep backend | awk '{print $1}' | head -1)
fi

if [ -n "$BACKEND_CONTAINER" ]; then
  echo "Found backend container: $BACKEND_CONTAINER"
  docker cp backend/app/api/signal_monitor.py $BACKEND_CONTAINER:/app/app/api/signal_monitor.py
  docker cp backend/app/services/signal_throttle.py $BACKEND_CONTAINER:/app/app/services/signal_throttle.py
  echo "✅ Files copied to container"
  docker-compose restart backend || docker compose restart backend || docker restart $BACKEND_CONTAINER
  echo "✅ Backend restarted"
else
  echo "❌ Backend container not found"
  echo "Available containers:"
  docker ps --format "{{.Names}}"
  exit 1
fi

echo "✅ Deployment complete!"
DEPLOY
else
  ssh_cmd $EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find the correct backend container name (try different patterns)
BACKEND_CONTAINER=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
if [ -z "$BACKEND_CONTAINER" ]; then
  BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
fi
if [ -z "$BACKEND_CONTAINER" ]; then
  BACKEND_CONTAINER=$(docker ps | grep backend | awk '{print $1}' | head -1)
fi

if [ -n "$BACKEND_CONTAINER" ]; then
  echo "Found backend container: $BACKEND_CONTAINER"
  docker cp backend/app/api/signal_monitor.py $BACKEND_CONTAINER:/app/app/api/signal_monitor.py
  docker cp backend/app/services/signal_throttle.py $BACKEND_CONTAINER:/app/app/services/signal_throttle.py
  echo "✅ Files copied to container"
  docker-compose restart backend || docker compose restart backend || docker restart $BACKEND_CONTAINER
  echo "✅ Backend restarted"
else
  echo "❌ Backend container not found"
  echo "Available containers:"
  docker ps --format "{{.Names}}"
  exit 1
fi

echo "✅ Deployment complete!"
DEPLOY
fi

echo ""
echo "🎉 Signal throttle fix deployed successfully!"
echo ""
echo "Changes:"
echo "  - Signal events now recorded immediately when detected (not just when alerts sent)"
echo "  - Fixed duplicate code in signal_throttle.py"
echo "  - Signal Throttle dashboard will now update in real-time"







