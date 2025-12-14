#!/bin/bash
# Script to restart backend - Run this directly on the AWS server
# Usage: Copy this to the server and run: bash restart_backend_on_server.sh

set -e

echo "🔄 Restarting backend on AWS..."
echo ""

cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Check if using Docker Compose
if command -v docker &> /dev/null && docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "📦 Using Docker Compose"
    echo "🔄 Restarting backend container..."
    docker compose --profile aws restart backend
    
    echo "⏳ Waiting 5 seconds..."
    sleep 5
    
    echo ""
    echo "📊 Backend status:"
    docker compose --profile aws ps backend
    
    echo ""
    echo "📋 Recent logs:"
    docker compose --profile aws logs --tail=30 backend
    
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "🐍 Using direct Python process"
    echo "🛑 Stopping existing backend..."
    pkill -f "uvicorn app.main:app"
    sleep 2
    
    cd backend
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    
    echo "🚀 Starting backend..."
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend restarted"
    echo ""
    echo "📋 Recent logs:"
    tail -30 backend.log
else
    echo "⚠️  No running backend process found"
    echo ""
    echo "Available Docker containers:"
    docker compose --profile aws ps 2>/dev/null || docker ps 2>/dev/null || echo "   Docker not available"
    echo ""
    echo "Python processes:"
    ps aux | grep uvicorn | grep -v grep || echo "   No uvicorn processes found"
fi

echo ""
echo "✅ Restart complete!"
echo ""
echo "🧪 Testing backend health..."
sleep 2
if curl -f --connect-timeout 5 http://localhost:8002/health >/dev/null 2>&1 || curl -f --connect-timeout 5 http://localhost:8000/api/health >/dev/null 2>&1; then
    echo "✅ Backend is healthy and responding"
else
    echo "⚠️  Backend health check failed - may need more time to start"
fi

