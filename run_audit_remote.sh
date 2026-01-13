#!/bin/bash
# Run audit remotely via SSH

set -e

# Configuration
EC2_HOST="${EC2_HOST:-175.41.189.249}"
EC2_USER="ubuntu"
REMOTE_DIR="/home/ubuntu/automated-trading-platform"

# Load SSH key configuration
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🔍 Running Audit on AWS Server"
echo "==============================="
echo "Host: $EC2_HOST"
echo ""

# Check if we can connect
echo "📡 Testing connection..."
if ! ssh_cmd "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ Cannot connect to $EC2_HOST"
    echo "   Please check:"
    echo "   1. SSH key is configured"
    echo "   2. Server is accessible"
    echo "   3. Security group allows SSH"
    exit 1
fi

echo "✅ Connected!"
echo ""

# Run audit
echo "📊 Running audit..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'AUDIT_SCRIPT'
cd /home/ubuntu/automated-trading-platform

# Find container
CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker ps -q --filter name=backend-aws | head -1)
if [ -z "$CONTAINER" ]; then
    CONTAINER=$(docker ps --format '{{.Names}}' | grep backend | head -1)
fi

if [ -z "$CONTAINER" ]; then
    echo "❌ Backend container not found"
    docker compose --profile aws ps
    exit 1
fi

echo "Container: $CONTAINER"
echo ""

# Run audit
echo "Running audit script..."
docker exec "$CONTAINER" python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24

echo ""
echo "=========================================="
echo "AUDIT REPORT"
echo "=========================================="
docker exec "$CONTAINER" cat docs/reports/no-alerts-no-trades-audit.md

echo ""
echo "=========================================="
echo "HEARTBEAT LOGS (last 5)"
echo "=========================================="
docker logs "$CONTAINER" 2>/dev/null | grep HEARTBEAT | tail -5 || echo "No heartbeat found yet"

echo ""
echo "=========================================="
echo "GLOBAL BLOCKERS (last 5)"
echo "=========================================="
docker logs "$CONTAINER" 2>/dev/null | grep GLOBAL_BLOCKER | tail -5 || echo "No global blockers found"
AUDIT_SCRIPT

echo ""
echo "✅ Audit complete!"





