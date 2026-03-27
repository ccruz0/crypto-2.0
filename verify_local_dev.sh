#!/bin/bash
set -euo pipefail

# Verification script for local backend-dev hot-reload setup
# This script verifies the backend-dev service is working correctly

cd ~/crypto-2.0

echo "🔍 Verifying local backend-dev setup..."
echo ""

# Fail early if Docker daemon is down
echo "1️⃣ Checking Docker daemon..."
if ! docker info >/dev/null 2>&1; then
    echo "   ❌ Docker daemon is not running"
    echo "   Please start Docker and try again"
    exit 1
fi
echo "   ✅ Docker daemon is running"

# Start services
echo ""
echo "2️⃣ Starting db + backend-dev services..."
docker compose --profile local up -d --build db backend-dev

# Wait for API to be ready (max 60s total)
echo ""
echo "3️⃣ Waiting for API to be ready (max 60s)..."
MAX_ATTEMPTS=30
ATTEMPT=0
SUCCESS=false

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    ATTEMPT=$((ATTEMPT + 1))
    if curl -fsS http://localhost:8002/api/health >/dev/null 2>&1; then
        SUCCESS=true
        break
    fi
    if [ $ATTEMPT -lt $MAX_ATTEMPTS ]; then
        echo "   Attempt $ATTEMPT/$MAX_ATTEMPTS: API not ready yet, waiting..."
        sleep 2
    fi
done

if [ "$SUCCESS" = false ]; then
    echo ""
    echo "   ❌ API did not become ready after $MAX_ATTEMPTS attempts (60s)"
    echo "   Check logs: cd backend && make dev-logs"
    exit 1
fi

# Test API and show response
echo ""
echo "4️⃣ Testing API health endpoint..."
HEALTH_RESPONSE=$(curl -sS http://localhost:8002/api/health)
echo "   ✅ API Response: $HEALTH_RESPONSE"

# Show status
echo ""
echo "5️⃣ Service status:"
docker compose --profile local ps

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ SUCCESS - Local backend-dev is running and healthy!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Quick commands:"
echo "   Start:    cd backend && make dev-up"
echo "   Logs:     cd backend && make dev-logs"
echo "   Restart:  cd backend && make dev-restart"
echo "   Stop:     cd backend && make dev-down"
echo ""
