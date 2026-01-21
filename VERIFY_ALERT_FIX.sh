#!/bin/bash
# Script to verify alert_enabled fix after deployment
# This script checks database state, API responses, and backend logs

set -e

echo "🔍 Alert System Fix - Verification Script"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
BACKEND_CONTAINER="${BACKEND_CONTAINER:-backend}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres_hardened}"
API_URL="${API_URL:-http://localhost:8000}"

echo -e "${BLUE}Configuration:${NC}"
echo "  Backend Container: $BACKEND_CONTAINER"
echo "  Postgres Container: $POSTGRES_CONTAINER"
echo "  API URL: $API_URL"
echo ""

# Step 1: Check Database State
echo -e "${BLUE}Step 1: Checking database state...${NC}"
echo ""

DB_RESULT=$(docker exec -i $POSTGRES_CONTAINER psql -U trader -d atp -t -A -F"," <<EOF
SELECT 
    COUNT(*)::text,
    COUNT(*) FILTER (WHERE alert_enabled = true)::text,
    COUNT(*) FILTER (WHERE alert_enabled = false)::text
FROM watchlist_items
WHERE is_deleted = false;
EOF
)

IFS=',' read -r TOTAL ENABLED DISABLED <<< "$DB_RESULT"

echo "  Total active coins: $TOTAL"
echo "  alert_enabled=True: $ENABLED"
echo "  alert_enabled=False: $DISABLED"
echo ""

if [ "$DISABLED" -eq "0" ]; then
    echo -e "${GREEN}✅ All active coins have alert_enabled=True${NC}"
else
    echo -e "${YELLOW}⚠️  $DISABLED coins still have alert_enabled=False${NC}"
    echo "  Run migration: ./RUN_ALERT_FIX_ON_AWS.sh"
fi
echo ""

# Step 2: Check API Alert Stats
echo -e "${BLUE}Step 2: Checking API alert stats...${NC}"
echo ""

if command -v curl &> /dev/null && command -v jq &> /dev/null; then
    API_RESPONSE=$(curl -s "$API_URL/api/dashboard/alert-stats" 2>/dev/null || echo "{}")
    
    if [ "$API_RESPONSE" != "{}" ]; then
        ALERT_ENABLED=$(echo "$API_RESPONSE" | jq -r '.alert_enabled // "N/A"')
        ALERT_DISABLED=$(echo "$API_RESPONSE" | jq -r '.alert_disabled // "N/A"')
        
        echo "  alert_enabled count: $ALERT_ENABLED"
        echo "  alert_disabled count: $ALERT_DISABLED"
        echo ""
        
        if [ "$ALERT_DISABLED" = "0" ]; then
            echo -e "${GREEN}✅ API reports all coins have alert_enabled=True${NC}"
        else
            echo -e "${YELLOW}⚠️  API reports $ALERT_DISABLED coins with alert_enabled=False${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  Could not fetch API response (API may not be running)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  curl/jq not available, skipping API check${NC}"
fi
echo ""

# Step 3: Check Backend Startup Logs
echo -e "${BLUE}Step 3: Checking backend startup logs...${NC}"
echo ""

if docker ps --format '{{.Names}}' | grep -q "$BACKEND_CONTAINER"; then
    STARTUP_LOGS=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep "STARTUP_ALERT_CONFIG" | head -5 || echo "")
    
    if [ -n "$STARTUP_LOGS" ]; then
        echo "  Recent startup configuration logs:"
        echo "$STARTUP_LOGS" | sed 's/^/    /'
        echo ""
        
        # Check for disabled count
        if echo "$STARTUP_LOGS" | grep -q "alert_enabled_false=0"; then
            echo -e "${GREEN}✅ Startup logs show alert_enabled_false=0${NC}"
        else
            DISABLED_COUNT=$(echo "$STARTUP_LOGS" | grep -oP 'alert_enabled_false=\K\d+' | head -1 || echo "unknown")
            echo -e "${YELLOW}⚠️  Startup logs show alert_enabled_false=$DISABLED_COUNT${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  No startup configuration logs found${NC}"
        echo "  Backend may not have been restarted since code deployment"
        echo "  Restart backend to see startup logs"
    fi
else
    echo -e "${YELLOW}⚠️  Backend container '$BACKEND_CONTAINER' not found${NC}"
fi
echo ""

# Step 4: Check Recent Alert Decisions
echo -e "${BLUE}Step 4: Checking recent alert decisions...${NC}"
echo ""

if docker ps --format '{{.Names}}' | grep -q "$BACKEND_CONTAINER"; then
    ALLOWED_COUNT=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -c "ALERT_ALLOWED" || echo "0")
    BLOCKED_COUNT=$(docker logs "$BACKEND_CONTAINER" 2>&1 | grep -c "ALERT_CHECK.*BLOCK.*ALERT_DISABLED" || echo "0")
    
    echo "  Recent ALERT_ALLOWED logs: $ALLOWED_COUNT"
    echo "  Recent ALERT_DISABLED blocks: $BLOCKED_COUNT"
    echo ""
    
    if [ "$ALLOWED_COUNT" -gt "0" ]; then
        echo -e "${GREEN}✅ Found $ALLOWED_COUNT ALERT_ALLOWED logs (alerts are being sent)${NC}"
    else
        echo -e "${YELLOW}⚠️  No ALERT_ALLOWED logs found (no alerts sent recently)${NC}"
    fi
    
    if [ "$BLOCKED_COUNT" -gt "0" ]; then
        echo -e "${YELLOW}⚠️  Found $BLOCKED_COUNT ALERT_DISABLED blocks (some alerts still blocked)${NC}"
        echo "  Recent blocked alerts:"
        docker logs "$BACKEND_CONTAINER" 2>&1 | grep "ALERT_CHECK.*BLOCK.*ALERT_DISABLED" | tail -5 | sed 's/^/    /'
    else
        echo -e "${GREEN}✅ No ALERT_DISABLED blocks found${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Backend container not available${NC}"
fi
echo ""

# Summary
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Summary${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

ALL_GOOD=true

if [ "$DISABLED" -ne "0" ]; then
    echo -e "${RED}❌ Database: $DISABLED coins still have alert_enabled=False${NC}"
    ALL_GOOD=false
else
    echo -e "${GREEN}✅ Database: All coins have alert_enabled=True${NC}"
fi

if docker ps --format '{{.Names}}' | grep -q "$BACKEND_CONTAINER"; then
    if docker logs "$BACKEND_CONTAINER" 2>&1 | grep -q "STARTUP_ALERT_CONFIG.*alert_enabled_false=0"; then
        echo -e "${GREEN}✅ Backend: Startup logs show correct configuration${NC}"
    else
        echo -e "${YELLOW}⚠️  Backend: Startup logs not found or show issues${NC}"
        echo "  (Restart backend to see startup logs)"
    fi
else
    echo -e "${YELLOW}⚠️  Backend: Container not running${NC}"
fi

echo ""

if [ "$ALL_GOOD" = true ]; then
    echo -e "${GREEN}✅ Verification complete - All checks passed!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Verification complete - Some issues found${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Run migration: ./RUN_ALERT_FIX_ON_AWS.sh"
    echo "  2. Restart backend container"
    echo "  3. Re-run this script to verify"
    exit 1
fi
