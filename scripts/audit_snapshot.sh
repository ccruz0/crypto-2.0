#!/bin/bash
# Audit Snapshot Script
# Provides a quick health check of the trading platform
# Can be run locally or on AWS
# 
# Usage:
#   ./scripts/audit_snapshot.sh          # Use Python version (preferred)
#   ./scripts/audit_snapshot.sh --bash   # Use bash version (fallback)

set -e

# Try Python version first (more reliable)
if [ "$1" != "--bash" ]; then
    if command -v python3 >/dev/null 2>&1; then
        # Determine script directory
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
        cd "$BASE_DIR"
        
        # Try to run Python version
        if [ -f "backend/app/tools/audit_snapshot.py" ]; then
            python3 backend/app/tools/audit_snapshot.py
            exit $?
        fi
    fi
fi

# Fallback to bash version

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Determine if running on AWS or locally
if [ -f "/home/ubuntu/automated-trading-platform/docker-compose.yml" ]; then
    # AWS
    BASE_DIR="/home/ubuntu/automated-trading-platform"
    API_URL="http://localhost:8002"
    FRONTEND_URL="http://localhost:3000"
    USE_DOCKER=true
else
    # Local
    BASE_DIR="${0%/*}/.."
    BASE_DIR=$(cd "$BASE_DIR" && pwd)
    API_URL="http://localhost:8002"
    FRONTEND_URL="http://localhost:3000"
    USE_DOCKER=false
fi

cd "$BASE_DIR"

echo "🔍 Audit Snapshot - $(date)"
echo "=================================="
echo ""

# Function to check service health
check_service_health() {
    local service=$1
    local url=$2
    
    if curl -s -f --max-time 5 "$url" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} $service: OK"
        return 0
    else
        echo -e "${RED}✗${NC} $service: FAILED"
        return 1
    fi
}

# Function to get count from API
get_api_count() {
    local endpoint=$1
    local field=$2
    
    response=$(curl -s --max-time 10 "$API_URL/api/$endpoint" 2>/dev/null || echo "{}")
    if [ "$response" != "{}" ]; then
        echo "$response" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('$field', 0))" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

# Check backend health
echo "📊 Service Health:"
BACKEND_OK=false
if check_service_health "Backend" "$API_URL/api/ping_fast"; then
    BACKEND_OK=true
fi

FRONTEND_OK=false
if check_service_health "Frontend" "$FRONTEND_URL" > /dev/null 2>&1; then
    FRONTEND_OK=true
    echo -e "${GREEN}✓${NC} Frontend: OK"
else
    echo -e "${YELLOW}⚠${NC} Frontend: Not accessible (may be normal if not running locally)"
fi

echo ""

# Check watchlist deduplication
echo "📋 Watchlist Status:"
if [ "$BACKEND_OK" = true ]; then
    # Get watchlist data
    WATCHLIST_DATA=$(curl -s --max-time 10 "$API_URL/api/dashboard/state" 2>/dev/null || echo "{}")
    
    if [ "$WATCHLIST_DATA" != "{}" ]; then
        # Count unique symbols
        SYMBOL_COUNT=$(echo "$WATCHLIST_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    watchlist = data.get('watchlist', [])
    symbols = set()
    for item in watchlist:
        symbol = item.get('symbol') or item.get('instrument_name', '')
        if symbol:
            symbols.add(symbol.upper())
    print(len(symbols))
except:
    print('0')
" 2>/dev/null || echo "0")
        
        # Count total items
        TOTAL_ITEMS=$(echo "$WATCHLIST_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    watchlist = data.get('watchlist', [])
    print(len(watchlist))
except:
    print('0')
" 2>/dev/null || echo "0")
        
        DUPLICATES=$((TOTAL_ITEMS - SYMBOL_COUNT))
        
        echo "  Symbols: $SYMBOL_COUNT"
        if [ "$DUPLICATES" -gt 0 ]; then
            echo -e "  ${YELLOW}⚠ Duplicates: $DUPLICATES${NC}"
        else
            echo -e "  ${GREEN}✓ Duplicates: 0${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠ Could not fetch watchlist data${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ Backend not available${NC}"
fi

echo ""

# Check alerts
echo "🔔 Active Alerts:"
if [ "$BACKEND_OK" = true ]; then
    ALERT_DATA=$(curl -s --max-time 10 "$API_URL/api/dashboard/state" 2>/dev/null || echo "{}")
    
    if [ "$ALERT_DATA" != "{}" ]; then
        BUY_ALERTS=$(echo "$ALERT_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    watchlist = data.get('watchlist', [])
    count = 0
    for item in watchlist:
        if item.get('buy_alert_enabled'):
            count += 1
    print(count)
except:
    print('0')
" 2>/dev/null || echo "0")
        
        SELL_ALERTS=$(echo "$ALERT_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    watchlist = data.get('watchlist', [])
    count = 0
    for item in watchlist:
        if item.get('sell_alert_enabled'):
            count += 1
    print(count)
except:
    print('0')
" 2>/dev/null || echo "0")
        
        echo "  BUY alerts: $BUY_ALERTS"
        echo "  SELL alerts: $SELL_ALERTS"
    else
        echo -e "  ${YELLOW}⚠ Could not fetch alert data${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ Backend not available${NC}"
fi

echo ""

# Check open orders
echo "📦 Open Orders:"
if [ "$BACKEND_OK" = true ]; then
    ORDERS_DATA=$(curl -s --max-time 10 "$API_URL/api/orders/open" 2>/dev/null || echo "{}")
    
    if [ "$ORDERS_DATA" != "{}" ]; then
        ORDER_COUNT=$(echo "$ORDERS_DATA" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    orders = data.get('orders', []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    print(len(orders))
except:
    print('0')
" 2>/dev/null || echo "0")
        
        echo "  Count: $ORDER_COUNT"
        if [ "$ORDER_COUNT" -gt 3 ]; then
            echo -e "  ${YELLOW}⚠ Warning: More than 3 open orders${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠ Could not fetch orders data${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ Backend not available${NC}"
fi

echo ""

# Check watchlist load time
echo "⏱️  Watchlist Load Time:"
if [ "$BACKEND_OK" = true ]; then
    START_TIME=$(date +%s%N)
    curl -s --max-time 10 "$API_URL/api/dashboard/state" > /dev/null 2>&1
    END_TIME=$(date +%s%N)
    ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))
    
    echo "  Load time: ${ELAPSED_MS}ms"
    if [ "$ELAPSED_MS" -gt 2000 ]; then
        echo -e "  ${YELLOW}⚠ Warning: Load time exceeds 2 seconds${NC}"
    else
        echo -e "  ${GREEN}✓ Load time acceptable${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ Backend not available${NC}"
fi

echo ""

# Check reports
echo "📊 Reports:"
if [ "$BACKEND_OK" = true ]; then
    # Check if reports endpoint exists and returns valid data
    REPORTS_DATA=$(curl -s --max-time 10 "$API_URL/api/reports/dashboard-data-integrity/latest" 2>/dev/null || echo "{}")
    
    if [ "$REPORTS_DATA" != "{}" ]; then
        # Check if response contains git errors (should not)
        if echo "$REPORTS_DATA" | grep -qi "git\|fatal\|error.*git"; then
            echo -e "  ${RED}✗ Reports contain git errors${NC}"
        else
            echo -e "  ${GREEN}✓ Reports OK (no git errors)${NC}"
        fi
    else
        echo -e "  ${YELLOW}⚠ Reports endpoint not available or empty${NC}"
    fi
else
    echo -e "  ${YELLOW}⚠ Backend not available${NC}"
fi

echo ""
echo "=================================="
echo "✅ Audit snapshot complete"

