#!/bin/bash
# Quick verification script for local dev environment
# Checks that backend and frontend are running and accessible

set -e

echo "🔍 Checking local development environment..."
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0

# Check port 8002 (backend)
echo -n "Checking backend port 8002... "
if lsof -i :8002 >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Listening${NC}"
else
    echo -e "${RED}✗ Not listening${NC}"
    echo "  → Start backend: docker compose --profile local up -d backend-dev"
    ERRORS=$((ERRORS + 1))
fi

# Check port 3000 (frontend)
echo -n "Checking frontend port 3000... "
if lsof -i :3000 >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Listening${NC}"
else
    echo -e "${RED}✗ Not listening${NC}"
    echo "  → Start frontend: cd frontend && npm run dev"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# Test backend health endpoint
echo -n "Testing backend /api/health... "
BACKEND_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/api/health || echo "000")
if [ "$BACKEND_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✓ OK (200)${NC}"
else
    echo -e "${RED}✗ Failed (HTTP $BACKEND_RESPONSE)${NC}"
    echo "  → Backend may not be running or not healthy"
    ERRORS=$((ERRORS + 1))
fi

# Test frontend
echo -n "Testing frontend http://localhost:3000... "
FRONTEND_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3000 || echo "000")
if [ "$FRONTEND_RESPONSE" = "200" ]; then
    echo -e "${GREEN}✓ OK (200)${NC}"
else
    echo -e "${RED}✗ Failed (HTTP $FRONTEND_RESPONSE)${NC}"
    echo "  → Frontend may not be running"
    ERRORS=$((ERRORS + 1))
fi

echo ""

# Summary
if [ $ERRORS -eq 0 ]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
    echo ""
    echo "Access the application:"
    echo "  Frontend: http://localhost:3000"
    echo "  Backend API: http://localhost:8002"
    echo "  API Docs: http://localhost:8002/docs"
    exit 0
else
    echo -e "${YELLOW}⚠️  Found $ERRORS issue(s)${NC}"
    echo ""
    echo "Common fixes:"
    echo "  1. Backend not running: docker compose --profile local up -d backend-dev"
    echo "  2. Frontend not running: cd frontend && npm run dev"
    echo "  3. Port conflicts: Check what's using ports 3000 or 8002 with 'lsof -i :3000' or 'lsof -i :8002'"
    exit 1
fi


