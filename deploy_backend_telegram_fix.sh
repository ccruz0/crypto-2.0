#!/bin/bash
# Deploy backend Telegram fix for min_price_change_pct by strategy

set -e

echo "🚀 Deploying Backend Telegram Fix"
echo "=================================="
echo ""

SERVER="ubuntu@175.41.189.249"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Check if key file exists
# No key discovery; using unified id_rsa via SSH_OPTS

echo "🔑 Using SSH key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo ""

echo "📦 Step 1: Syncing backend files (telegram_commands.py)..."
rsync_cmd \
  --include='app/services/telegram_commands.py' \
  --exclude='*' \
  ./backend/app/services/telegram_commands.py \
  $SERVER:~/crypto-2.0/backend/app/services/telegram_commands.py

echo ""
echo "🔄 Step 2: Restarting backend service..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/crypto-2.0

# Check if using Docker Compose
if command -v docker-compose &> /dev/null || command -v docker &> /dev/null; then
    echo "🐳 Docker detected - restarting backend container..."
    
    # Stop and remove backend container to free port, then start fresh
    echo "🛑 Stopping and removing backend container..."
    if command -v docker-compose &> /dev/null; then
        docker-compose stop backend 2>/dev/null || docker-compose -f docker-compose.yml stop backend
        docker-compose rm -f backend 2>/dev/null || docker-compose -f docker-compose.yml rm -f backend
        sleep 3
        echo "🚀 Starting backend container..."
        docker-compose up -d backend 2>/dev/null || docker-compose -f docker-compose.yml up -d backend
    # Try docker compose as plugin
    elif docker compose version &> /dev/null; then
        docker compose stop backend 2>/dev/null || docker compose -f docker-compose.yml stop backend
        docker compose rm -f backend 2>/dev/null || docker compose -f docker-compose.yml rm -f backend
        sleep 3
        echo "🚀 Starting backend container..."
        docker compose up -d backend 2>/dev/null || docker compose -f docker-compose.yml up -d backend
    else
        echo "⚠️  Docker Compose not found, trying direct Docker..."
        CONTAINER=$(docker ps -a --filter "name=backend" --format "{{.Names}}" | head -1)
        if [ -n "$CONTAINER" ]; then
            echo "🛑 Stopping and removing container: $CONTAINER"
            docker stop $CONTAINER 2>/dev/null || true
            docker rm -f $CONTAINER 2>/dev/null || true
            sleep 3
            echo "🚀 Container removed. You may need to recreate it manually."
        else
            echo "⚠️  Backend container not found"
        fi
    fi
    
    # Check if port 8002 is still in use
    echo "🔍 Checking port 8002..."
    PORT_CHECK=$(netstat -tuln 2>/dev/null | grep :8002 || ss -tuln 2>/dev/null | grep :8002 || lsof -i :8002 2>/dev/null || echo "")
    if [ -n "$PORT_CHECK" ]; then
        echo "⚠️  Warning: Port 8002 is still in use. You may need to manually free it."
        echo "   To find what's using it: sudo lsof -i :8002"
    else
        echo "✅ Port 8002 is free"
    fi
else
    # Not using Docker - check for direct uvicorn process
    echo "🔍 Checking for uvicorn process..."
    UvicornPID=$(pgrep -f "uvicorn app.main:app" | head -1)
    
    if [ -n "$UvicornPID" ]; then
        echo "🔄 Restarting uvicorn process (PID: $UvicornPID)..."
        kill $UvicornPID
        sleep 2
        
        # Start backend in background
        cd backend
        if [ -d "venv" ]; then
            source venv/bin/activate
        fi
        nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
        echo "✅ Backend restarted (PID: $!)"
    else
        echo "⚠️  No uvicorn process found. Backend may not be running."
        echo "💡 To start backend manually:"
        echo "   cd ~/crypto-2.0/backend"
        echo "   source venv/bin/activate"
        echo "   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
    fi
fi

echo ""
echo "✅ Backend restart completed"
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📱 Test the Telegram bot by sending /menu and clicking '⚙️ Min Price Change %'"
echo "   It should now show 'Select Strategy' instead of 'Select Coin'"

