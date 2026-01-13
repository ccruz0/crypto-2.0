#!/bin/bash
set -e

echo "=========================================="
echo "Monitoring Refresh - Restart & Test Script"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check if backend is running
check_backend() {
    echo -e "${YELLOW}Checking if backend is running...${NC}"
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Backend is running${NC}"
        return 0
    else
        echo -e "${RED}❌ Backend is not running${NC}"
        return 1
    fi
}

# Start backend
start_backend() {
    echo -e "${YELLOW}Starting backend...${NC}"
    cd backend
    
    # Check if virtual environment exists
    if [ ! -d "venv" ]; then
        echo -e "${YELLOW}Creating virtual environment...${NC}"
        python3 -m venv venv
    fi
    
    source venv/bin/activate
    
    # Install dependencies if needed
    if [ ! -f "venv/.deps_installed" ]; then
        echo -e "${YELLOW}Installing dependencies...${NC}"
        pip install -q -r requirements.txt
        touch venv/.deps_installed
    fi
    
    # Check if backend is already running
    if check_backend; then
        echo -e "${YELLOW}Backend is already running. Restarting...${NC}"
        pkill -f "uvicorn app.main:app" || true
        sleep 2
    fi
    
    # Start backend in background
    echo -e "${YELLOW}Starting backend server...${NC}"
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > backend.log 2>&1 &
    BACKEND_PID=$!
    echo "Backend PID: $BACKEND_PID"
    
    # Wait for backend to start
    echo -e "${YELLOW}Waiting for backend to start...${NC}"
    for i in {1..30}; do
        if check_backend; then
            echo -e "${GREEN}✅ Backend started successfully!${NC}"
            return 0
        fi
        sleep 1
    done
    
    echo -e "${RED}❌ Backend failed to start${NC}"
    echo "Last 20 lines of backend.log:"
    tail -20 backend.log
    return 1
}

# Run tests
run_tests() {
    echo ""
    echo "=========================================="
    echo "Running Tests"
    echo "=========================================="
    echo ""
    
    cd backend
    
    # Activate virtual environment
    source venv/bin/activate
    
    # Run test script
    echo -e "${YELLOW}Running monitoring refresh tests...${NC}"
    python3 test_monitoring_refresh.py
    
    TEST_EXIT_CODE=$?
    
    if [ $TEST_EXIT_CODE -eq 0 ]; then
        echo -e "${GREEN}✅ All tests passed!${NC}"
    else
        echo -e "${RED}❌ Some tests failed${NC}"
    fi
    
    return $TEST_EXIT_CODE
}

# Test API endpoints manually
test_endpoints() {
    echo ""
    echo "=========================================="
    echo "Manual API Endpoint Tests"
    echo "=========================================="
    echo ""
    
    BASE_URL="http://localhost:8000/api"
    
    echo -e "${YELLOW}Test 1: Basic monitoring summary${NC}"
    response=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$BASE_URL/monitoring/summary")
    http_code=$(echo "$response" | grep "HTTP_CODE" | cut -d: -f2)
    body=$(echo "$response" | sed '/HTTP_CODE/d')
    
    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}✅ Status: $http_code${NC}"
        signals_timestamp=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('signals_last_calculated', 'null'))")
        active_alerts=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('active_alerts', 0))")
        echo "   Active Alerts: $active_alerts"
        echo "   Signals Last Calculated: $signals_timestamp"
    else
        echo -e "${RED}❌ Status: $http_code${NC}"
    fi
    
    echo ""
    echo -e "${YELLOW}Test 2: Force refresh${NC}"
    response=$(curl -s -w "\nHTTP_CODE:%{http_code}" "$BASE_URL/monitoring/summary?force_refresh=true")
    http_code=$(echo "$response" | grep "HTTP_CODE" | cut -d: -f2)
    body=$(echo "$response" | sed '/HTTP_CODE/d')
    
    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}✅ Status: $http_code${NC}"
        signals_timestamp=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('signals_last_calculated', 'null'))")
        active_alerts=$(echo "$body" | python3 -c "import sys, json; data=json.load(sys.stdin); print(data.get('active_alerts', 0))")
        echo "   Active Alerts: $active_alerts"
        echo "   Signals Last Calculated: $signals_timestamp"
        
        if [ "$signals_timestamp" != "null" ] && [ "$signals_timestamp" != "None" ]; then
            echo -e "${GREEN}✅ Timestamp provided: $signals_timestamp${NC}"
        else
            echo -e "${YELLOW}⚠️  No timestamp (may be expected if no watchlist items)${NC}"
        fi
    else
        echo -e "${RED}❌ Status: $http_code${NC}"
    fi
}

# Main execution
main() {
    # Check if we should start backend
    if ! check_backend; then
        read -p "Backend is not running. Start it now? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            start_backend
            if [ $? -ne 0 ]; then
                echo -e "${RED}Failed to start backend. Exiting.${NC}"
                exit 1
            fi
        else
            echo -e "${YELLOW}Skipping backend start. Make sure backend is running before running tests.${NC}"
        fi
    fi
    
    # Wait a moment for backend to be ready
    sleep 2
    
    # Run automated tests
    run_tests
    TEST_RESULT=$?
    
    # Run manual endpoint tests
    test_endpoints
    
    echo ""
    echo "=========================================="
    echo "Summary"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo "1. Open frontend in browser: http://localhost:3000"
    echo "2. Navigate to Monitoring tab"
    echo "3. Test the 'Refresh Signals' button"
    echo "4. Verify timestamp appears after refresh"
    echo "5. Verify signals match Watchlist tab"
    echo ""
    
    if [ $TEST_RESULT -eq 0 ]; then
        echo -e "${GREEN}✅ All automated tests passed!${NC}"
        exit 0
    else
        echo -e "${YELLOW}⚠️  Some tests failed. Check output above.${NC}"
        exit 1
    fi
}

# Run main function
main


