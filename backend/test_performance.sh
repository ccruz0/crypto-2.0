#!/bin/bash

# Script de verificación de rendimiento
# Uso: ./test_performance.sh

echo "🚀 Testing Backend Performance"
echo "================================"
echo ""

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

BASE_URL="http://localhost:8002"

# Función para testear un endpoint
test_endpoint() {
    local endpoint=$1
    local name=$2
    local expected_max_ms=$3
    
    echo -n "Testing $name... "
    
    result=$(curl -w "\n%{time_starttransfer}" -sS -o /dev/null "$BASE_URL$endpoint" 2>&1)
    time_ms=$(echo "$result" | tail -1 | awk '{print $1 * 1000}')
    
    if (( $(echo "$time_ms < $expected_max_ms" | bc -l) )); then
        echo -e "${GREEN}✅ ${time_ms}ms${NC} (expected < ${expected_max_ms}ms)"
        return 0
    else
        echo -e "${RED}❌ ${time_ms}ms${NC} (expected < ${expected_max_ms}ms)"
        return 1
    fi
}

# Test 1: Health check
echo "1. Health Check"
test_endpoint "/health" "Health endpoint" 100
health_result=$?
echo ""

# Test 2: Ping fast
echo "2. Ping Fast"
test_endpoint "/ping_fast" "Ping fast endpoint" 100
ping_result=$?
echo ""

# Test 3: Dashboard state
echo "3. Dashboard State"
test_endpoint "/api/dashboard/state" "Dashboard state endpoint" 1000
dashboard_result=$?
echo ""

# Resumen
echo "================================"
echo "Summary:"
echo ""

if [ $health_result -eq 0 ] && [ $ping_result -eq 0 ] && [ $dashboard_result -eq 0 ]; then
    echo -e "${GREEN}✅ All endpoints are performing well!${NC}"
    exit 0
else
    echo -e "${YELLOW}⚠️  Some endpoints are slow. Check logs for details.${NC}"
    echo ""
    echo "Check logs with:"
    echo "  cd /Users/carloscruz/automated-trading-platform && bash scripts/aws_backend_logs.sh --tail 100 | grep PERF"
    exit 1
fi

