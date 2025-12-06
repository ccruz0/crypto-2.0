#!/bin/bash
# Dashboard Health Diagnostic Script - Complete System Check
# Usage: bash scripts/debug_dashboard_remote.sh
#
# This script connects to the AWS server and runs comprehensive diagnostics
# to identify why the dashboard at https://dashboard.hilovivo.com is failing.
#
# It checks:
# - All Docker containers (status, health, restarts)
# - Backend API connectivity (internal and external)
# - Frontend availability
# - Nginx reverse proxy
# - Database connectivity
# - Network connectivity between containers
# - Recent error logs

set -euo pipefail

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}=========================================="
echo "Dashboard Health Diagnostic"
echo "==========================================${NC}"
echo ""
echo -e "${CYAN}Connecting to:${NC} $REMOTE_HOST"
echo -e "${CYAN}Remote path:${NC} $REMOTE_PATH"
echo ""

# Track overall status
ERRORS=0
WARNINGS=0

# Run diagnostics on remote server
ssh "$REMOTE_HOST" "cd $REMOTE_PATH && bash -s" << 'REMOTE_SCRIPT'
set -euo pipefail

# Colors (redefined for remote execution)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}=== DOCKER COMPOSE STATUS ===${NC}"
COMPOSE_OUTPUT=$(docker compose --profile aws ps 2>&1)
echo "$COMPOSE_OUTPUT"
echo ""

# Parse container statuses
BACKEND_STATUS=$(echo "$COMPOSE_OUTPUT" | grep "backend-aws" | awk '{print $NF}' || echo "not found")
MARKET_UPDATER_STATUS=$(echo "$COMPOSE_OUTPUT" | grep "market-updater" | awk '{print $NF}' || echo "not found")
DB_STATUS=$(echo "$COMPOSE_OUTPUT" | grep "postgres_hardened" | awk '{print $NF}' || echo "not found")
GLUETUN_STATUS=$(echo "$COMPOSE_OUTPUT" | grep "gluetun" | awk '{print $NF}' || echo "not found")
FRONTEND_STATUS=$(echo "$COMPOSE_OUTPUT" | grep "frontend-aws" | awk '{print $NF}' || echo "not found")

echo -e "${BLUE}=== CONTAINER HEALTH DETAILS ===${NC}"
echo ""

# Backend health
echo -e "${CYAN}Backend-aws Health:${NC}"
BACKEND_CONTAINER=$(docker ps --filter 'name=backend-aws' --format '{{.Names}}' | head -1)
if [ -n "$BACKEND_CONTAINER" ]; then
    RESTART_COUNT=$(docker inspect "$BACKEND_CONTAINER" --format='{{.RestartCount}}' 2>/dev/null || echo "0")
    HEALTH_STATUS=$(docker inspect "$BACKEND_CONTAINER" --format='{{.State.Health.Status}}' 2>/dev/null || echo "none")
    HEALTH_JSON=$(docker inspect "$BACKEND_CONTAINER" --format='{{json .State.Health}}' 2>/dev/null || echo "{}")
    
    if [ "$RESTART_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Restart count: $RESTART_COUNT${NC}"
    fi
    
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}✅ Status: HEALTHY${NC}"
        FAILING_STREAK=$(echo "$HEALTH_JSON" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('FailingStreak', 0))" 2>/dev/null || echo "0")
        if [ "$FAILING_STREAK" -gt 0 ]; then
            echo -e "${YELLOW}⚠️  Failing streak: $FAILING_STREAK${NC}"
        fi
    elif [ "$HEALTH_STATUS" = "unhealthy" ]; then
        echo -e "${RED}❌ Status: UNHEALTHY${NC}"
        echo "$HEALTH_JSON" | python3 -m json.tool 2>/dev/null | head -20 || echo "$HEALTH_JSON"
    elif [ "$HEALTH_STATUS" = "starting" ]; then
        echo -e "${YELLOW}⏳ Status: STARTING (may take up to 180s)${NC}"
    else
        echo -e "${YELLOW}⚠️  No healthcheck configured${NC}"
    fi
else
    echo -e "${RED}❌ Backend container not found${NC}"
fi
echo ""

# Market-updater health
echo -e "${CYAN}Market-updater Health:${NC}"
MARKET_UPDATER_CONTAINER=$(docker ps --filter 'name=market-updater' --format '{{.Names}}' | head -1)
if [ -n "$MARKET_UPDATER_CONTAINER" ]; then
    RESTART_COUNT=$(docker inspect "$MARKET_UPDATER_CONTAINER" --format='{{.RestartCount}}' 2>/dev/null || echo "0")
    HEALTH_STATUS=$(docker inspect "$MARKET_UPDATER_CONTAINER" --format='{{.State.Health.Status}}' 2>/dev/null || echo "none")
    HEALTH_JSON=$(docker inspect "$MARKET_UPDATER_CONTAINER" --format='{{json .State.Health}}' 2>/dev/null || echo "{}")
    
    if [ "$RESTART_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}⚠️  Restart count: $RESTART_COUNT${NC}"
    fi
    
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}✅ Status: HEALTHY${NC}"
        FAILING_STREAK=$(echo "$HEALTH_JSON" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('FailingStreak', 0))" 2>/dev/null || echo "0")
        if [ "$FAILING_STREAK" -gt 0 ]; then
            echo -e "${YELLOW}⚠️  Failing streak: $FAILING_STREAK${NC}"
        fi
    elif [ "$HEALTH_STATUS" = "unhealthy" ]; then
        echo -e "${RED}❌ Status: UNHEALTHY${NC}"
        echo "$HEALTH_JSON" | python3 -m json.tool 2>/dev/null | head -20 || echo "$HEALTH_JSON"
        echo -e "${YELLOW}⚠️  NOTE: Market-updater healthcheck failure does NOT break the dashboard${NC}"
    elif [ "$HEALTH_STATUS" = "starting" ]; then
        echo -e "${YELLOW}⏳ Status: STARTING (may take up to 30s)${NC}"
    else
        echo -e "${YELLOW}⚠️  No healthcheck configured${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Market-updater container not found (may not be running)${NC}"
fi
echo ""

# Database health
echo -e "${CYAN}Database Health:${NC}"
DB_CONTAINER=$(docker ps --filter 'name=postgres_hardened' --format '{{.Names}}' | head -1)
if [ -n "$DB_CONTAINER" ]; then
    HEALTH_STATUS=$(docker inspect "$DB_CONTAINER" --format='{{.State.Health.Status}}' 2>/dev/null || echo "none")
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}✅ Status: HEALTHY${NC}"
    elif [ "$HEALTH_STATUS" = "unhealthy" ]; then
        echo -e "${RED}❌ Status: UNHEALTHY${NC}"
    else
        echo -e "${YELLOW}⚠️  Status: $HEALTH_STATUS${NC}"
    fi
else
    echo -e "${RED}❌ Database container not found${NC}"
fi
echo ""

# Gluetun health
echo -e "${CYAN}Gluetun (VPN) Health:${NC}"
GLUETUN_CONTAINER=$(docker ps --filter 'name=gluetun' --format '{{.Names}}' | head -1)
if [ -n "$GLUETUN_CONTAINER" ]; then
    HEALTH_STATUS=$(docker inspect "$GLUETUN_CONTAINER" --format='{{.State.Health.Status}}' 2>/dev/null || echo "none")
    if [ "$HEALTH_STATUS" = "healthy" ]; then
        echo -e "${GREEN}✅ Status: HEALTHY${NC}"
    elif [ "$HEALTH_STATUS" = "unhealthy" ]; then
        echo -e "${RED}❌ Status: UNHEALTHY${NC}"
        echo -e "${YELLOW}⚠️  WARNING: VPN failure may prevent backend from making external API calls${NC}"
    else
        echo -e "${YELLOW}⚠️  Status: $HEALTH_STATUS${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Gluetun container not found${NC}"
fi
echo ""

echo -e "${BLUE}=== API CONNECTIVITY TESTS ===${NC}"
echo ""

# Test backend from host (bypassing nginx)
echo -e "${CYAN}Backend API (Host → Backend):${NC}"
if HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 http://127.0.0.1:8002/api/config 2>/dev/null); then
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✅ HTTP $HTTP_CODE - Backend is reachable from host${NC}"
    else
        echo -e "${RED}❌ HTTP $HTTP_CODE - Backend returned error${NC}"
    fi
else
    echo -e "${RED}❌ Connection failed or timeout${NC}"
fi
echo ""

# Test backend from inside container (Docker network)
echo -e "${CYAN}Backend API (Container → Backend via Docker network):${NC}"
if [ -n "$MARKET_UPDATER_CONTAINER" ]; then
    if docker exec "$MARKET_UPDATER_CONTAINER" python3 -c "import urllib.request; resp = urllib.request.urlopen('http://backend-aws:8002/ping_fast', timeout=5); print('HTTP', resp.getcode())" 2>/dev/null; then
        echo -e "${GREEN}✅ Backend is reachable from container via Docker network${NC}"
    else
        echo -e "${RED}❌ Backend is NOT reachable from container (Docker network issue)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Cannot test (market-updater container not available)${NC}"
fi
echo ""

# Test database connectivity from backend
echo -e "${CYAN}Database Connectivity (Backend → DB):${NC}"
if [ -n "$BACKEND_CONTAINER" ]; then
    if docker exec "$BACKEND_CONTAINER" python3 -c "import psycopg2; conn = psycopg2.connect('postgresql://trader:${POSTGRES_PASSWORD:-traderpass}@db:5432/atp', connect_timeout=5); conn.close()" 2>/dev/null; then
        echo -e "${GREEN}✅ Database is reachable from backend${NC}"
    else
        echo -e "${RED}❌ Database connection failed from backend${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Cannot test (backend container not available)${NC}"
fi
echo ""

echo -e "${BLUE}=== EXTERNAL ENDPOINT TESTS ===${NC}"
echo ""

# Test API endpoint via domain
echo -e "${CYAN}Dashboard API (/api/config via domain):${NC}"
if HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://dashboard.hilovivo.com/api/config 2>/dev/null); then
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✅ HTTP $HTTP_CODE - API endpoint is working${NC}"
    elif [ "$HTTP_CODE" = "502" ]; then
        echo -e "${RED}❌ HTTP $HTTP_CODE - Bad Gateway (nginx cannot reach backend)${NC}"
    elif [ "$HTTP_CODE" = "504" ]; then
        echo -e "${RED}❌ HTTP $HTTP_CODE - Gateway Timeout (backend too slow)${NC}"
    else
        echo -e "${YELLOW}⚠️  HTTP $HTTP_CODE - Unexpected status${NC}"
    fi
else
    echo -e "${RED}❌ Connection failed or timeout${NC}"
fi
echo ""

# Test root endpoint via domain
echo -e "${CYAN}Dashboard Root (/) via domain:${NC}"
if HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 https://dashboard.hilovivo.com/ 2>/dev/null); then
    if [ "$HTTP_CODE" = "200" ]; then
        echo -e "${GREEN}✅ HTTP $HTTP_CODE - Frontend is serving${NC}"
    elif [ "$HTTP_CODE" = "502" ]; then
        echo -e "${RED}❌ HTTP $HTTP_CODE - Bad Gateway (nginx cannot reach frontend)${NC}"
    elif [ "$HTTP_CODE" = "504" ]; then
        echo -e "${RED}❌ HTTP $HTTP_CODE - Gateway Timeout${NC}"
    else
        echo -e "${YELLOW}⚠️  HTTP $HTTP_CODE - Unexpected status${NC}"
    fi
else
    echo -e "${RED}❌ Connection failed or timeout${NC}"
fi
echo ""

echo -e "${BLUE}=== NGINX STATUS ===${NC}"
if systemctl is-active --quiet nginx 2>/dev/null; then
    echo -e "${GREEN}✅ Nginx is running${NC}"
else
    echo -e "${RED}❌ Nginx is NOT running${NC}"
fi
echo ""

echo -e "${BLUE}=== RECENT ERROR LOGS ===${NC}"
echo ""

# Backend error logs
echo -e "${CYAN}Backend Errors (last 50 lines):${NC}"
docker compose --profile aws logs --tail=50 backend-aws 2>/dev/null | grep -iE "error|exception|traceback|failed|fatal" | tail -20 || echo "No errors found in recent logs"
echo ""

# Market-updater error logs
echo -e "${CYAN}Market-updater Errors (last 50 lines):${NC}"
docker compose --profile aws logs --tail=50 market-updater 2>/dev/null | grep -iE "error|exception|traceback|failed|fatal" | tail -20 || echo "No errors found in recent logs"
echo ""

# Nginx error log
echo -e "${CYAN}Nginx Errors (last 20 lines):${NC}"
sudo tail -20 /var/log/nginx/error.log 2>/dev/null | grep -iE "error|502|504|upstream|refused" || echo "No recent nginx errors"
echo ""

echo -e "${BLUE}=== DIAGNOSTIC COMPLETE ===${NC}"
REMOTE_SCRIPT

echo ""
echo -e "${BLUE}=========================================="
echo "Next Steps:"
echo "==========================================${NC}"
echo "1. Review container statuses above"
echo "2. Check health indicators - should all be ✅ HEALTHY"
echo "3. Verify API connectivity tests pass"
echo "4. Review error logs for exceptions or connection issues"
echo "5. See docs/runbooks/dashboard_healthcheck.md for detailed troubleshooting"
echo ""
echo -e "${CYAN}Quick Reference:${NC}"
echo "- Backend unhealthy → Check backend logs, database connection, startup errors"
echo "- API 502 → Nginx cannot reach backend (check backend container status)"
echo "- Root 502 → Frontend container may be down"
echo "- Market-updater unhealthy → Does NOT affect dashboard (informational only)"
echo ""
