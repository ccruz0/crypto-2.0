#!/bin/bash
# Complete Alert Fix Deployment Script
# This script deploys code, runs migration, and verifies the fix

set -e

echo "🚀 Alert Fix - Complete Deployment"
echo "=================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
REMOTE_HOST="${REMOTE_HOST:-hilovivo-aws}"
PROJECT_DIR="${PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

echo -e "${BLUE}Configuration:${NC}"
echo "  Remote Host: $REMOTE_HOST"
echo "  Project Dir: $PROJECT_DIR"
echo ""

# Check SSH connection
echo -e "${BLUE}Checking SSH connection...${NC}"
if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo -e "${RED}❌ Cannot connect to $REMOTE_HOST${NC}"
    echo "  Make sure SSH is configured correctly"
    echo "  Or set REMOTE_HOST environment variable"
    exit 1
fi
echo -e "${GREEN}✅ SSH connection OK${NC}"
echo ""

# Ask for confirmation
echo -e "${YELLOW}This will:${NC}"
echo "  1. Deploy latest code from git (build & restart backend)"
echo "  2. Run database migration (set alert_enabled=True for all coins)"
echo "  3. Verify deployment and migration"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 0
fi

echo ""

# Step 1: Deploy Code
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 1: Deploying Code${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

ssh "$REMOTE_HOST" << 'DEPLOY_CODE'
cd /home/ubuntu/automated-trading-platform

echo "📥 Pulling latest code..."
git fetch --all
git checkout main
git reset --hard origin/main

CURRENT_COMMIT=$(git rev-parse --short HEAD)
echo "✅ Git state: HEAD = $CURRENT_COMMIT"
echo ""

echo "🐳 Building backend..."
docker compose --profile aws build backend-aws

echo ""
echo "🚀 Restarting backend..."
docker compose --profile aws up -d --force-recreate --no-deps backend-aws

echo ""
echo "⏳ Waiting for services to start (15 seconds)..."
sleep 15

echo ""
echo "✅ Checking service status..."
docker compose --profile aws ps backend-aws

echo ""
echo "🔍 Verifying backend health..."
if curl -sS -m 10 http://127.0.0.1:8002/health > /dev/null 2>&1; then
    echo "✅ Backend is healthy"
else
    echo "⚠️  Health check failed (service may still be starting)"
fi

echo ""
echo -e "\033[0;32m✅ Code deployment complete!\033[0m"
DEPLOY_CODE

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Code deployment failed${NC}"
    exit 1
fi

echo ""
echo ""

# Step 2: Run Database Migration
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 2: Running Database Migration${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

ssh "$REMOTE_HOST" << 'RUN_MIGRATION'
cd /home/ubuntu/automated-trading-platform

if [ ! -f "./RUN_ALERT_FIX_ON_AWS.sh" ]; then
    echo "❌ Migration script not found: RUN_ALERT_FIX_ON_AWS.sh"
    echo "   Make sure the script is in the repository"
    exit 1
fi

echo "🔧 Executing database migration..."
bash ./RUN_ALERT_FIX_ON_AWS.sh

MIGRATION_EXIT=$?
if [ $MIGRATION_EXIT -ne 0 ]; then
    echo "❌ Migration script failed"
    exit $MIGRATION_EXIT
fi

echo ""
echo -e "\033[0;32m✅ Database migration complete!\033[0m"
RUN_MIGRATION

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Database migration failed${NC}"
    echo "  You may need to run the migration manually"
    exit 1
fi

echo ""
echo ""

# Step 3: Verify Deployment
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Step 3: Verifying Deployment${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

ssh "$REMOTE_HOST" << 'VERIFY'
cd /home/ubuntu/automated-trading-platform

if [ ! -f "./VERIFY_ALERT_FIX.sh" ]; then
    echo "⚠️  Verification script not found, running manual checks..."
    
    echo ""
    echo "📊 Checking database state..."
    docker exec -i postgres_hardened psql -U trader -d atp -t -A -F"," <<SQL
SELECT 
    COUNT(*)::text,
    COUNT(*) FILTER (WHERE alert_enabled = true)::text,
    COUNT(*) FILTER (WHERE alert_enabled = false)::text
FROM watchlist_items
WHERE is_deleted = false;
SQL
    
    echo ""
    echo "📋 Checking startup logs..."
    BACKEND_CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo "")
    if [ -n "$BACKEND_CONTAINER" ]; then
        docker logs "$BACKEND_CONTAINER" 2>&1 | grep "STARTUP_ALERT_CONFIG" | head -5 || echo "  No startup config logs found yet"
    else
        echo "  Backend container not found"
    fi
else
    echo "🔍 Running verification script..."
    bash ./VERIFY_ALERT_FIX.sh
fi
VERIFY

echo ""
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Deployment Complete!${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo -e "${YELLOW}Next Steps:${NC}"
echo "  1. Check startup logs for configuration summary:"
echo "     ssh $REMOTE_HOST 'docker logs \$(docker compose --profile aws ps -q backend-aws) | grep STARTUP_ALERT_CONFIG | head -30'"
echo ""
echo "  2. Monitor alert decisions in logs:"
echo "     ssh $REMOTE_HOST 'docker logs \$(docker compose --profile aws ps -q backend-aws) | grep ALERT_ALLOWED | tail -20'"
echo ""
echo "  3. Check API alert stats:"
echo "     curl -s https://dashboard.hilovivo.com/api/dashboard/alert-stats | jq '{alert_enabled, alert_disabled}'"
echo ""
echo -e "${GREEN}✅ All deployment steps completed!${NC}"
