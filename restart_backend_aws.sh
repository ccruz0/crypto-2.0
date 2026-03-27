#!/bin/bash
# Script to restart backend on AWS server

set -e

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔄 Restarting backend on AWS..."
echo ""

ssh_cmd "$EC2_USER@$EC2_HOST" << 'RESTART_SCRIPT'
cd ~/crypto-2.0

# Check if using Docker Compose
if docker compose --profile aws ps backend 2>/dev/null | grep -q "Up"; then
    echo "🔄 Restarting backend container..."
    docker compose --profile aws restart backend
    echo "✅ Backend container restarted"
    
    # Wait a bit and check status
    sleep 5
    echo ""
    echo "📊 Backend status:"
    docker compose --profile aws ps backend
    
    echo ""
    echo "📋 Recent logs:"
    docker compose --profile aws logs --tail=20 backend
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "🔄 Restarting uvicorn process..."
    pkill -f "uvicorn app.main:app"
    sleep 2
    
    cd ~/crypto-2.0/backend
    source venv/bin/activate 2>/dev/null || true
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    
    sleep 3
    echo "✅ Backend restarted"
    echo ""
    echo "📋 Recent logs:"
    tail -20 backend.log
else
    echo "⚠️  No running backend process found"
    echo "Available Docker containers:"
    docker compose --profile aws ps 2>/dev/null || docker ps
fi
RESTART_SCRIPT

echo ""
echo "✅ Restart complete!"

