#!/bin/bash
# AWS Deploy-by-Commit Script
# Standardized deployment script for AWS EC2
# This script ensures clean git state and deploys using docker compose --profile aws

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory and repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$REPO_ROOT"

echo "=========================================="
echo "AWS Deploy-by-Commit"
echo "=========================================="
echo ""

# Verify we're in the right directory
if [ ! -f "docker-compose.yml" ]; then
    echo -e "${RED}❌ ERROR: docker-compose.yml not found. Are you in the repo root?${NC}"
    exit 1
fi

# Verify .env.aws exists (required for AWS deployment)
if [ ! -f ".env.aws" ]; then
    echo -e "${YELLOW}⚠️  WARNING: .env.aws not found. Deployment may fail if required env vars are missing.${NC}"
fi

echo "📁 Repository root: $REPO_ROOT"
echo ""

# Step 1: Fetch latest from origin
echo "📥 Fetching latest from origin..."
git fetch --all || {
    echo -e "${RED}❌ ERROR: Failed to fetch from origin${NC}"
    exit 1
}

# Step 2: Checkout main branch
echo "🔀 Checking out main branch..."
git checkout main || {
    echo -e "${RED}❌ ERROR: Failed to checkout main branch${NC}"
    exit 1
}

# Step 3: Reset to origin/main (ensures clean state)
echo "🔄 Resetting to origin/main..."
git reset --hard origin/main || {
    echo -e "${RED}❌ ERROR: Failed to reset to origin/main${NC}"
    exit 1
}

# Step 4: Show current state
CURRENT_COMMIT=$(git rev-parse HEAD)
CURRENT_COMMIT_SHORT=$(git rev-parse --short HEAD)
echo ""
echo "✅ Git state:"
echo "   HEAD: $CURRENT_COMMIT_SHORT ($CURRENT_COMMIT)"
echo "   Branch: $(git branch --show-current)"
echo "   Status: $(git status --short | wc -l | tr -d ' ') uncommitted files"
echo ""

# Step 5: Pull Docker images (if applicable)
echo "🐳 Pulling Docker images..."
docker compose --profile aws pull || {
    echo -e "${YELLOW}⚠️  WARNING: docker compose pull failed (may be expected if using local builds)${NC}"
}

# Step 6: Build and start services
echo ""
echo "🚀 Building and starting services..."
docker compose --profile aws up -d --build || {
    echo -e "${RED}❌ ERROR: Failed to start services${NC}"
    exit 1
}

# Step 7: Wait for services to start
echo ""
echo "⏳ Waiting for services to start (15 seconds)..."
sleep 15

# Step 8: Verify services
echo ""
echo "✅ Service status:"
docker compose --profile aws ps || {
    echo -e "${RED}❌ ERROR: Failed to get service status${NC}"
    exit 1
}

# Step 9: Health check
echo ""
echo "🏥 Health check..."
HEALTH_URL="http://localhost:8002/api/health/system"
HEALTH_RESPONSE=$(curl -sS "$HEALTH_URL" || echo "")

if [ -z "$HEALTH_RESPONSE" ]; then
    echo -e "${RED}❌ ERROR: Health endpoint not responding${NC}"
    echo "   URL: $HEALTH_URL"
    exit 1
fi

# Extract key health metrics (using jq if available, otherwise grep)
if command -v jq &> /dev/null; then
    MARKET_UPDATER_STATUS=$(echo "$HEALTH_RESPONSE" | jq -r '.market_updater.status // "UNKNOWN"')
    MARKET_DATA_STALE=$(echo "$HEALTH_RESPONSE" | jq -r '.market_data.stale_symbols // "UNKNOWN"')
    MARKET_DATA_MAX_AGE=$(echo "$HEALTH_RESPONSE" | jq -r '.market_data.max_age_minutes // "UNKNOWN"')
    TELEGRAM_ENABLED=$(echo "$HEALTH_RESPONSE" | jq -r '.telegram.enabled // "UNKNOWN"')
    
    echo "   Market Updater: $MARKET_UPDATER_STATUS"
    echo "   Market Data Stale Symbols: $MARKET_DATA_STALE"
    echo "   Market Data Max Age: $MARKET_DATA_MAX_AGE minutes"
    echo "   Telegram Enabled: $TELEGRAM_ENABLED"
    
    # Fail if market_updater is not PASS
    if [ "$MARKET_UPDATER_STATUS" != "PASS" ]; then
        echo -e "${RED}❌ ERROR: Market updater status is not PASS${NC}"
        exit 1
    fi
    
    # Fail if market data has stale symbols
    if [ "$MARKET_DATA_STALE" != "0" ] && [ "$MARKET_DATA_STALE" != "null" ]; then
        echo -e "${RED}❌ ERROR: Market data has stale symbols: $MARKET_DATA_STALE${NC}"
        exit 1
    fi
else
    echo "   Health endpoint responded (jq not available for parsing)"
    echo "   Response preview: $(echo "$HEALTH_RESPONSE" | head -c 200)..."
fi

# Step 10: Optional cleanup (guarded)
if [ "${CLEANUP_DOCKER_IMAGES:-false}" = "true" ]; then
    echo ""
    echo "🧹 Cleaning up unused Docker images..."
    docker image prune -f || {
        echo -e "${YELLOW}⚠️  WARNING: Docker image prune failed${NC}"
    }
fi

# Summary
echo ""
echo "=========================================="
echo -e "${GREEN}✅ Deployment completed successfully!${NC}"
echo "=========================================="
echo ""
echo "📊 Summary:"
echo "   Git HEAD: $CURRENT_COMMIT_SHORT"
echo "   Services: $(docker compose --profile aws ps --format json | jq -r 'length' 2>/dev/null || echo 'N/A') running"
echo "   Health: OK"
echo ""
echo "🔍 Verify deployment:"
echo "   curl -s http://localhost:8002/api/health/system | jq ."
echo ""

