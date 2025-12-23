#!/bin/bash
# Deploy all Telegram fixes (portfolio TP/SL, /start menu, duplicate keyboard fix)

set -e

echo "🚀 Deploying Telegram Fixes"
echo "============================"
echo ""
echo "Fixes included:"
echo "  ✅ Portfolio message: TP/SL values and open position indicators"
echo "  ✅ /start command: Shows menu with inline buttons"
echo "  ✅ Duplicate keyboard: Removes persistent keyboard"
echo ""

SERVER="ubuntu@175.41.189.249"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔑 Using SSH key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo ""

echo "📦 Step 1: Pulling latest code from Git..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform
git pull origin main
echo "✅ Code updated"
ENDSSH

echo ""
echo "🔄 Step 2: Restarting backend service..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform/backend

# Check if using Docker Compose
if command -v docker-compose &> /dev/null || docker compose version &> /dev/null 2>/dev/null; then
    echo "🐳 Docker detected - restarting backend container..."
    
    if command -v docker-compose &> /dev/null; then
        docker-compose restart backend 2>/dev/null || docker-compose -f docker-compose.yml restart backend
    elif docker compose version &> /dev/null 2>/dev/null; then
        docker compose restart backend 2>/dev/null || docker compose -f docker-compose.yml restart backend
    fi
    
    echo "⏳ Waiting for backend to start..."
    sleep 5
    
    # Check if backend is running
    if docker-compose ps backend 2>/dev/null | grep -q "Up" || docker compose ps backend 2>/dev/null | grep -q "Up"; then
        echo "✅ Backend container is running"
    else
        echo "⚠️  Backend container status unclear, check logs with: docker compose logs backend"
    fi
else
    # Not using Docker - restart uvicorn directly
    echo "🔄 Restarting uvicorn process..."
    
    # Stop existing process
    if pgrep -f "uvicorn app.main:app" > /dev/null; then
        echo "🛑 Stopping existing backend..."
        pkill -f "uvicorn app.main:app"
        sleep 2
    fi
    
    # Activate venv and start
    if [ -d "venv" ]; then
        source venv/bin/activate
    else
        echo "📦 Creating virtual environment..."
        python3 -m venv venv
        source venv/bin/activate
        pip install -r requirements.txt
    fi
    
    # Start backend
    echo "🚀 Starting backend on port 8002..."
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > backend.log 2>&1 &
    sleep 2
    
    # Check if started
    if pgrep -f "uvicorn app.main:app" > /dev/null; then
        echo "✅ Backend restarted (PID: $(pgrep -f 'uvicorn app.main:app'))"
    else
        echo "⚠️  Backend may not have started, check logs: tail -f backend.log"
    fi
fi

echo ""
echo "✅ Backend restart completed"
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📱 Test the fixes:"
echo "   1. Send /start to Telegram bot - should show menu with inline buttons (no duplication)"
echo "   2. Send /portfolio - should show TP/SL values and open position indicators"
echo "   3. Verify menu buttons appear in all cases"
echo ""
echo "🔍 To check backend logs:"
echo "   ssh $SERVER 'cd ~/automated-trading-platform/backend && tail -f backend.log'"
echo "   Or if using Docker:"
echo "   ssh $SERVER 'cd ~/automated-trading-platform && docker compose logs -f backend'"
echo ""

