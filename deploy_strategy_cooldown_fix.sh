#!/bin/bash

EC2_HOST="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Strategy Cooldown and Telegram Origin Fix"
echo "======================================================="
echo ""

# Files to deploy
FILES=(
  "backend/trading_config.json"
  "backend/app/services/config_loader.py"
  "backend/app/services/signal_evaluator.py"
  "backend/app/services/signal_monitor.py"
  "backend/app/api/signal_monitor.py"
)

echo "📦 Syncing backend files..."
for file in "${FILES[@]}"; do
  echo "  - Syncing $file"
  rsync_cmd "$file" "$EC2_USER@$EC2_HOST:~/automated-trading-platform/$file" 2>&1 | grep -v "error:" | grep -v "warning:" || true
done

echo ""
echo "🐳 Deploying to Docker containers..."

# Step 2: Deploy via SSH
ssh_cmd $EC2_USER@$EC2_HOST 'bash -s' << 'REMOTE_SCRIPT'
cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Find backend container
BACKEND=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)
echo "Backend container: ${BACKEND:-NOT FOUND}"

if [ -n "$BACKEND" ]; then
  # Copy files to container
  docker cp backend/trading_config.json $BACKEND:/app/trading_config.json 2>/dev/null || docker cp backend/trading_config.json $BACKEND:/app/backend/trading_config.json
  docker cp backend/app/services/config_loader.py $BACKEND:/app/app/services/config_loader.py
  docker cp backend/app/services/signal_evaluator.py $BACKEND:/app/app/services/signal_evaluator.py
  docker cp backend/app/services/signal_monitor.py $BACKEND:/app/app/services/signal_monitor.py
  docker cp backend/app/api/signal_monitor.py $BACKEND:/app/app/api/signal_monitor.py 2>/dev/null || echo "Note: signal_monitor.py in api may not exist"
  
  echo "✅ Files copied to container"
  
  # Restart backend
  echo "🔄 Restarting backend container..."
  docker restart $BACKEND
  echo "✅ Backend restarted"
  
  # Wait for service to be healthy
  echo "⏳ Waiting for backend to be ready..."
  sleep 10
  
  # Check health
  if curl -f http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "✅ Backend is healthy"
  else
    echo "⚠️  Backend health check failed (may need more time)"
  fi
else
  echo "❌ Backend container not found"
  exit 1
fi

echo "✅ Deployment complete!"
REMOTE_SCRIPT

echo ""
echo "✅ All done!"




