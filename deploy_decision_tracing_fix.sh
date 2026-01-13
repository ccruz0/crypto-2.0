#!/bin/bash
# Deploy BUY SIGNAL Decision Tracing Fix to AWS
# This script syncs the updated code files and restarts the market-updater process

set -e

# Configuration
# Note: Check AWS Console for current IP if connection fails
EC2_HOST_PRIMARY="47.130.143.159"  # Current Elastic IP (from AUDIT_AWS.md)
EC2_HOST_ALTERNATIVE="54.254.150.31"
EC2_HOST_TERTIARY="175.41.189.249"
EC2_USER="ubuntu"
PROJECT_DIR="automated-trading-platform"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Determine which host to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo -e "${GREEN}✅ Using primary host: $EC2_HOST${NC}"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo -e "${GREEN}✅ Using alternative host: $EC2_HOST${NC}"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_TERTIARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_TERTIARY"
    echo -e "${GREEN}✅ Using tertiary host: $EC2_HOST${NC}"
else
    echo -e "${RED}❌ Cannot connect to any host${NC}"
    echo -e "${YELLOW}💡 Check AWS Console for current instance IP and update EC2_HOST_PRIMARY in this script${NC}"
    exit 1
fi

echo "========================================="
echo "Deploying Decision Tracing Fix"
echo "========================================="
echo ""

# Step 1: Sync the changed files
echo -e "${GREEN}📦 Syncing updated code files...${NC}"
rsync_cmd \
    backend/app/api/routes_monitoring.py \
    backend/app/services/signal_monitor.py \
    backend/app/utils/decision_reason.py \
    "$EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/"

echo ""
echo -e "${GREEN}✅ Files synced successfully${NC}"
echo ""

# Step 2: Restart services on AWS
echo -e "${GREEN}🔄 Restarting services on AWS...${NC}"
ssh_cmd "$EC2_USER@$EC2_HOST" << 'ENDSSH'
cd ~/automated-trading-platform/backend

# Find and restart market-updater process (run_updater.py)
echo "🔄 Restarting market-updater (run_updater.py)..."
if pgrep -f "run_updater.py" > /dev/null; then
    echo "   Stopping existing market-updater process..."
    pkill -f "run_updater.py" || true
    sleep 2
fi

# Start market-updater in background
echo "   Starting market-updater..."
nohup python3 run_updater.py > market_updater.log 2>&1 &
sleep 2

# Verify it's running
if pgrep -f "run_updater.py" > /dev/null; then
    echo "   ✅ Market-updater is running (PID: $(pgrep -f 'run_updater.py'))"
else
    echo "   ⚠️  Warning: Market-updater may not have started. Check market_updater.log"
fi

# Restart backend API if it's running directly (not in Docker)
if pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "🔄 Restarting backend API..."
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    sleep 2
    echo "   ✅ Backend API restarted"
fi

echo ""
echo "✅ Service restarts complete"
ENDSSH

echo ""
echo -e "${GREEN}✅ Deployment complete!${NC}"
echo ""
echo "Next steps:"
echo "1. Verify the diagnostics endpoint:"
echo "   curl http://${EC2_HOST}:8000/api/diagnostics/recent-buy-signals?limit=10"
echo ""
echo "2. Check market-updater logs:"
echo "   ssh $EC2_USER@$EC2_HOST 'tail -50 ~/automated-trading-platform/backend/market_updater.log'"
echo ""
echo "3. Monitor for new BUY SIGNAL messages with decision tracing"
