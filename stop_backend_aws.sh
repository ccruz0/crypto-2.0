#!/bin/bash
# Script to stop backend on AWS server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

EC2_HOST="47.130.143.159"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🛑 Stopping backend on AWS..."
echo ""

ssh_cmd "$EC2_USER@$EC2_HOST" << 'STOP_SCRIPT'
cd ~/automated-trading-platform

# Check if using Docker Compose
if docker ps | grep -q "backend-aws"; then
    echo "🛑 Stopping backend container..."
    docker stop automated-trading-platform-backend-aws-1 2>/dev/null || \
    compose --profile aws stop backend 2>/dev/null || \
    docker stop $(docker ps -q --filter "name=backend") 2>/dev/null
    echo "✅ Backend container stopped"
    
    # Wait a bit and check status
    sleep 3
    echo ""
    echo "📊 Backend status:"
    docker ps | grep backend || echo "   Backend container is stopped"
elif pgrep -f "uvicorn app.main:app" > /dev/null || pgrep -f "gunicorn.*app.main:app" > /dev/null; then
    echo "🛑 Stopping uvicorn process..."
    pkill -f "uvicorn app.main:app"
    sleep 2
    
    echo "✅ Backend process stopped"
    echo ""
    echo "📋 Verifying no uvicorn processes:"
    pgrep -f "uvicorn app.main:app" && echo "⚠️  Process still running" || echo "✅ No uvicorn processes found"
else
    echo "⚠️  No running backend process found"
    echo ""
    echo "Available Docker containers:"
    compose --profile aws ps 2>/dev/null || docker ps
    echo ""
    echo "Python processes:"
    ps aux | grep uvicorn | grep -v grep || echo "   No uvicorn processes found"
fi
STOP_SCRIPT

echo ""
echo "✅ Stop complete!"
echo ""
echo "💡 Backend on AWS is now stopped. You can now run local tests without 409 conflicts."
echo "💡 To restart AWS backend later, run: ./restart_backend_aws.sh"
