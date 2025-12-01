#!/bin/bash
# Deploy and test Trading toggle fix on AWS
#
# Usage:
#   ./scripts/deploy_and_test_trading_toggle.sh [SYMBOL]
#
# Example:
#   ./scripts/deploy_and_test_trading_toggle.sh ALGO_USDT

set -e

SYMBOL="${1:-ALGO_USDT}"
SYMBOL_UPPER=$(echo "$SYMBOL" | tr '[:lower:]' '[:upper:]')

echo "=========================================="
echo "Trading Toggle Fix - Deploy & Test Script"
echo "=========================================="
echo ""
echo "Symbol: $SYMBOL_UPPER"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to run command on AWS
run_aws() {
    sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && $1'"
}

# Use python3 instead of python
PYTHON_CMD="python3"

# Step 1: Build
echo -e "${YELLOW}Step 1: Building backend and frontend...${NC}"
run_aws "docker compose build backend-aws frontend-aws"
echo -e "${GREEN}✓ Build completed${NC}\n"

# Step 2: Deploy
echo -e "${YELLOW}Step 2: Deploying services...${NC}"
run_aws "docker compose up -d backend-aws frontend-aws"
echo -e "${GREEN}✓ Deployment completed${NC}\n"

# Wait for services to be ready
echo -e "${YELLOW}Waiting for services to be ready...${NC}"
sleep 5

# Step 3: Check current state
echo -e "${YELLOW}Step 3: Checking current state for $SYMBOL_UPPER...${NC}"
run_aws "$PYTHON_CMD -m backend.scripts.debug_watchlist_trade_enabled $SYMBOL_UPPER"
echo ""

# Step 4: Run verification script
echo -e "${YELLOW}Step 4: Running end-to-end verification...${NC}"
run_aws "$PYTHON_CMD -m backend.scripts.verify_trading_toggle_end_to_end $SYMBOL_UPPER"
echo ""

# Step 5: Monitor logs
echo -e "${YELLOW}Step 5: Monitoring backend logs (last 50 lines)...${NC}"
echo -e "${YELLOW}Looking for DASHBOARD_UPDATE_BY_SYMBOL and MONITOR_TRADE_FLAG...${NC}"
run_aws "docker logs automated-trading-platform-backend-aws-1 --tail 50 | grep -E 'DASHBOARD_UPDATE_BY_SYMBOL|MONITOR_TRADE_FLAG' || echo 'No matching logs found yet'"
echo ""

# Step 6: Instructions
echo -e "${GREEN}=========================================="
echo "Deployment completed!"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "1. Open the Dashboard in your browser"
echo "2. For $SYMBOL_UPPER:"
echo "   - Set Trading = NO"
echo "   - Refresh page and verify it stays NO"
echo "   - Run: ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && python3 -m backend.scripts.debug_watchlist_trade_enabled $SYMBOL_UPPER'"
echo "   - Verify trade_enabled=False for canonical row"
echo ""
echo "3. Then set Trading = YES"
echo "   - Refresh page and verify it stays YES"
echo "   - Run the debug script again"
echo "   - Verify trade_enabled=True for the SAME canonical row id"
echo ""
echo "4. Monitor logs for consistency:"
echo "   ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker logs automated-trading-platform-backend-aws-1 --tail 200 | grep -E \"DASHBOARD_UPDATE_BY_SYMBOL|MONITOR_TRADE_FLAG\"'"
echo ""
echo "5. Verify the same id appears in both logs (DASHBOARD_UPDATE_BY_SYMBOL and MONITOR_TRADE_FLAG)"
echo ""

