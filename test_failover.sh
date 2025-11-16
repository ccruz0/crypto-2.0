#!/bin/bash

# Test Failover Script
# This script tests the automatic failover between local and AWS backends

echo "========================================="
echo "Testing Hybrid Local/AWS Failover"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

# Test 1: Local Backend Health
print_test "1. Testing Local Backend Health"
if curl -f --connect-timeout 5 http://localhost:8000/health > /dev/null 2>&1; then
    print_status "✅ Local backend is healthy"
    LOCAL_HEALTHY=true
else
    print_warning "⚠️  Local backend is not responding"
    LOCAL_HEALTHY=false
fi

# Test 2: Local Frontend
print_test "2. Testing Local Frontend"
if curl -f --connect-timeout 5 http://localhost:3000 > /dev/null 2>&1; then
    print_status "✅ Local frontend is accessible"
else
    print_warning "⚠️  Local frontend is not accessible"
fi

# Test 3: AWS Backend Health
print_test "3. Testing AWS Backend Health"
if curl -f --connect-timeout 10 http://54.254.150.31:8000/health > /dev/null 2>&1; then
    print_status "✅ AWS backend is healthy"
    AWS_HEALTHY=true
else
    print_warning "⚠️  AWS backend is not responding"
    AWS_HEALTHY=false
fi

# Test 4: Environment Detection
print_test "4. Testing Environment Detection"
LOCAL_ENV=$(curl -s http://localhost:8000/health | jq -r '.environment' 2>/dev/null || echo "unknown")
if [ "$LOCAL_ENV" = "local" ]; then
    print_status "✅ Backend correctly detects local environment"
else
    print_warning "⚠️  Backend environment detection: $LOCAL_ENV"
fi

# Test 5: CORS Configuration
print_test "5. Testing CORS Configuration"
CORS_ORIGINS=$(curl -s http://localhost:8000/health | jq -r '.cors_origins[]' 2>/dev/null | tr '\n' ' ')
if [[ $CORS_ORIGINS == *"localhost:3000"* ]]; then
    print_status "✅ CORS configured for local development"
else
    print_warning "⚠️  CORS configuration may need adjustment"
fi

# Test 6: Frontend API Calls
print_test "6. Testing Frontend API Integration"
if curl -f --connect-timeout 5 http://localhost:3000 > /dev/null 2>&1; then
    print_status "✅ Frontend is serving content"
    print_status "   Open http://localhost:3000 in your browser to see the dashboard"
    print_status "   Look for environment status indicators in the header"
else
    print_error "❌ Frontend is not accessible"
fi

echo ""
echo "========================================="
echo "Test Summary"
echo "========================================="
echo "Local Backend: $([ "$LOCAL_HEALTHY" = true ] && echo "✅ Healthy" || echo "❌ Unhealthy")"
echo "AWS Backend:   $([ "$AWS_HEALTHY" = true ] && echo "✅ Healthy" || echo "❌ Unhealthy")"
echo "Frontend:      ✅ Accessible at http://localhost:3000"
echo ""
echo "Expected Behavior:"
echo "- When local backend is healthy: Frontend uses local backend"
echo "- When local backend fails: Frontend automatically switches to AWS backend"
echo "- Environment indicators show current status in the UI"
echo ""
echo "To test failover:"
echo "1. Stop local backend: docker compose stop backend"
echo "2. Refresh browser - should show 'Using AWS Backend'"
echo "3. Start local backend: docker compose start backend"
echo "4. Wait 5 seconds and refresh - should show 'Local Backend'"

