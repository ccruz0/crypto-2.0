#!/bin/bash
# Check for publicly exposed ports that should be internal-only
# This script verifies that database and other sensitive ports are not exposed publicly

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "=========================================="
echo "Public Port Security Check"
echo "=========================================="
echo ""

ISSUES_FOUND=0

# Check for database port 5432 on host
echo "🔍 Checking for database port 5432 exposure..."
DB_LISTENERS=$(ss -lntp 2>/dev/null | grep ':5432' || true)

if [ -n "$DB_LISTENERS" ]; then
    echo -e "${RED}❌ CRITICAL: Port 5432 (PostgreSQL) is listening on host interface${NC}"
    echo "   Found listeners:"
    echo "$DB_LISTENERS" | sed 's/^/   /'
    echo ""
    echo "   ⚠️  Database should only be accessible via Docker network (db:5432)"
    echo "   Fix: Remove any 'ports: 5432:5432' mapping from docker-compose.yml"
    echo "   Fix: Ensure AWS Security Group does NOT allow inbound 5432 from 0.0.0.0/0"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
else
    echo -e "${GREEN}✅ Port 5432 not listening on host (database is internal-only)${NC}"
fi

echo ""

# Check for other sensitive ports that might be exposed
SENSITIVE_PORTS=(3306 27017 6379 5984)  # MySQL, MongoDB, Redis, CouchDB
for PORT in "${SENSITIVE_PORTS[@]}"; do
    LISTENERS=$(ss -lntp 2>/dev/null | grep ":$PORT" || true)
    if [ -n "$LISTENERS" ]; then
        echo -e "${YELLOW}⚠️  Port $PORT is listening (verify if this should be public)${NC}"
        echo "$LISTENERS" | sed 's/^/   /'
    fi
done

echo ""

# Verify backend can still connect to database via Docker network
echo "🔍 Verifying backend can connect to database via Docker network..."
if command -v docker >/dev/null 2>&1; then
    # Try to find backend container
    BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1 || true)
    
    if [ -n "$BACKEND_CONTAINER" ]; then
        if docker exec "$BACKEND_CONTAINER" python3 -c "import psycopg2; conn = psycopg2.connect('postgresql://trader:traderpass@db:5432/atp', connect_timeout=5); conn.close()" 2>/dev/null; then
            echo -e "${GREEN}✅ Backend can connect to database via Docker network${NC}"
        else
            echo -e "${RED}❌ Backend cannot connect to database${NC}"
            echo "   Check database container status: docker compose --profile aws ps db"
            ISSUES_FOUND=$((ISSUES_FOUND + 1))
        fi
    else
        echo -e "${YELLOW}⚠️  Backend container not found (skipping connection test)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Docker not available (skipping connection test)${NC}"
fi

echo ""

# AWS Security Group reminder
echo "📋 AWS Security Group Verification (Manual Check Required):"
echo "   1. AWS Console → EC2 → Security Groups"
echo "   2. Find the security group attached to your EC2 instance"
echo "   3. Check Inbound Rules:"
echo "      ✅ Port 22 (SSH) - Should be restricted to your IP or VPN"
echo "      ✅ Port 80/443 (HTTP/HTTPS) - Can be open to 0.0.0.0/0"
echo "      ❌ Port 5432 (PostgreSQL) - Must NOT be open to 0.0.0.0/0"
echo "      ❌ Port 8002 (Backend API) - Should NOT be open (use Nginx/443 instead)"
echo "   4. If port 5432 is open, remove the inbound rule immediately"

echo ""

# Summary
if [ $ISSUES_FOUND -eq 0 ]; then
    echo -e "${GREEN}=========================================="
    echo "✅ Security check passed"
    echo "==========================================${NC}"
    echo ""
    echo "⚠️  Remember to verify AWS Security Group settings manually (see above)"
    exit 0
else
    echo -e "${RED}=========================================="
    echo "❌ Security issues found: $ISSUES_FOUND"
    echo "==========================================${NC}"
    echo ""
    echo "Fix the issues above before proceeding with deployment."
    exit 1
fi
