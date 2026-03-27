#!/bin/bash

EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Try to determine which host to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Using primary host: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Using alternative host: $EC2_HOST"
else
    echo "❌ Cannot connect to either host"
    echo "   Tried: $EC2_HOST_PRIMARY and $EC2_HOST_ALTERNATIVE"
    echo "   Please check AWS Console or try manual connection"
    exit 1
fi

echo "🚀 Deploying Strategy Cooldown and Telegram Origin Fix"
echo "======================================================="
echo ""

# Files to deploy
FILES=(
  "backend/trading_config.json"
  "backend/app/services/config_loader.py"
  "backend/app/services/signal_evaluator.py"
  "backend/app/services/signal_monitor.py"
)

echo "📦 Syncing backend files..."
for file in "${FILES[@]}"; do
  echo "  - Syncing $file"
  rsync_cmd "$file" "$EC2_USER@$EC2_HOST:~/crypto-2.0/$file" 2>&1 | grep -v "error:" | grep -v "warning:" || true
done

# Also sync signal_monitor.py from api if it exists
if [ -f "backend/app/api/signal_monitor.py" ]; then
  echo "  - Syncing backend/app/api/signal_monitor.py"
  rsync_cmd "backend/app/api/signal_monitor.py" "$EC2_USER@$EC2_HOST:~/crypto-2.0/backend/app/api/signal_monitor.py" 2>&1 | grep -v "error:" | grep -v "warning:" || true
fi

echo ""
echo "🐳 Deploying to Docker containers..."

ssh_cmd $EC2_USER@$EC2_HOST 'bash -s' << 'REMOTE_SCRIPT'
cd ~/crypto-2.0 || cd /home/ubuntu/crypto-2.0

# Find backend container
BACKEND=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
echo "Backend container: ${BACKEND:-NOT FOUND}"

if [ -n "$BACKEND" ]; then
  # Copy files to container
  echo "📋 Copying files to container..."
  docker cp backend/trading_config.json $BACKEND:/app/trading_config.json 2>/dev/null || docker cp backend/trading_config.json $BACKEND:/app/backend/trading_config.json 2>/dev/null || echo "  ⚠️  Could not copy trading_config.json"
  docker cp backend/app/services/config_loader.py $BACKEND:/app/app/services/config_loader.py 2>/dev/null || echo "  ⚠️  Could not copy config_loader.py"
  docker cp backend/app/services/signal_evaluator.py $BACKEND:/app/app/services/signal_evaluator.py 2>/dev/null || echo "  ⚠️  Could not copy signal_evaluator.py"
  docker cp backend/app/services/signal_monitor.py $BACKEND:/app/app/services/signal_monitor.py 2>/dev/null || echo "  ⚠️  Could not copy signal_monitor.py"
  
  if [ -f "backend/app/api/signal_monitor.py" ]; then
    docker cp backend/app/api/signal_monitor.py $BACKEND:/app/app/api/signal_monitor.py 2>/dev/null || echo "  ⚠️  Could not copy api/signal_monitor.py"
  fi
  
  echo "✅ Files copied to container"
  
  # Restart backend
  echo "🔄 Restarting backend container..."
  docker restart $BACKEND
  echo "✅ Backend restarted"
  
  # Wait for service to be healthy
  echo "⏳ Waiting for backend to be ready..."
  sleep 15
  
  # Check health
  if curl -f http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "✅ Backend is healthy"
  else
    echo "⚠️  Backend health check failed (may need more time to start)"
    echo "    Check logs with: docker logs $BACKEND | tail -50"
  fi
else
  echo "❌ Backend container not found"
  echo "   Available containers:"
  docker ps --format "{{.Names}}"
  exit 1
fi

echo "✅ Deployment complete!"
REMOTE_SCRIPT

echo ""
echo "✅ Deployment finished!"




