#!/bin/bash
# Deploy Telegram portfolio message fix (TP/SL values and open position indicators)

set -e

echo "🚀 Deploying Telegram Portfolio Fix"
echo "===================================="
echo ""

SERVER="ubuntu@175.41.189.249"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔑 Using SSH key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo ""

echo "📦 Step 1: Pulling latest code from Git..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/crypto-2.0
git pull origin main
echo "✅ Code updated"
ENDSSH

echo ""
echo "🔄 Step 2: Restarting backend service..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/crypto-2.0/backend

# Check if using Docker Compose
if command -v docker-compose &> /dev/null || docker compose version &> /dev/null 2>/dev/null; then
    echo "🐳 Docker detected - restarting backend container..."
    
    if command -v docker-compose &> /dev/null; then
        docker-compose restart backend 2>/dev/null || docker-compose -f docker-compose.yml restart backend
    elif docker compose version &> /dev/null 2>/dev/null; then
        docker compose restart backend 2>/dev/null || docker compose -f docker-compose.yml restart backend
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
    echo "✅ Backend restarted (PID: $!)"
fi

echo ""
echo "✅ Backend restart completed"
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📱 Test the Telegram bot by sending /portfolio"
echo "   You should now see:"
echo "   - Open position indicators (🔒 Open Position / 💤 Available)"
echo "   - Actual TP/SL values instead of $0.00"
echo "   - Menu buttons in all cases (including errors)"
echo ""

