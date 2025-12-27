#!/bin/bash

# Test script for report endpoints
# This script tests both backend endpoints directly and via nginx

set -e

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
BACKEND_URL="${BACKEND_URL:-http://localhost:8002}"
NGINX_URL="${NGINX_URL:-https://dashboard.hilovivo.com}"
TEST_DATE="${TEST_DATE:-20251203}"  # Default test date, change if needed

echo "🧪 Testing Report Endpoints"
echo "============================"
echo "Backend URL: $BACKEND_URL"
echo "Nginx URL: $NGINX_URL"
echo "Test Date: $TEST_DATE"
echo ""

# Function to test an endpoint
test_endpoint() {
    local url=$1
    local description=$2
    local expected_status=${3:-200}
    
    echo -n "Testing: $description... "
    
    if response=$(curl -s -w "\n%{http_code}" -o /tmp/response_body.txt "$url" 2>/dev/null); then
        http_code=$(echo "$response" | tail -n1)
        if [ "$http_code" = "$expected_status" ]; then
            echo -e "${GREEN}✅ PASS${NC} (HTTP $http_code)"
            return 0
        else
            echo -e "${RED}❌ FAIL${NC} (Expected HTTP $expected_status, got HTTP $http_code)"
            if [ -f /tmp/response_body.txt ]; then
                echo "Response body:"
                cat /tmp/response_body.txt
            fi
            return 1
        fi
    else
        echo -e "${RED}❌ FAIL${NC} (Connection error)"
        return 1
    fi
}

# Function to test endpoint with HEAD method
test_endpoint_head() {
    local url=$1
    local description=$2
    local expected_status=${3:-200}
    
    echo -n "Testing (HEAD): $description... "
    
    if http_code=$(curl -s -o /dev/null -w "%{http_code}" -X HEAD "$url" 2>/dev/null); then
        if [ "$http_code" = "$expected_status" ]; then
            echo -e "${GREEN}✅ PASS${NC} (HTTP $http_code)"
            return 0
        else
            echo -e "${RED}❌ FAIL${NC} (Expected HTTP $expected_status, got HTTP $http_code)"
            return 1
        fi
    else
        echo -e "${RED}❌ FAIL${NC} (Connection error)"
        return 1
    fi
}

# Track test results
PASSED=0
FAILED=0

echo "📋 Testing Backend Endpoints Directly"
echo "--------------------------------------"

# Test watchlist consistency latest
if test_endpoint "$BACKEND_URL/api/monitoring/reports/watchlist-consistency/latest" \
    "Watchlist Consistency Latest (Backend)"; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test watchlist consistency dated
if test_endpoint "$BACKEND_URL/api/monitoring/reports/watchlist-consistency/$TEST_DATE" \
    "Watchlist Consistency Dated (Backend)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test watchlist dedup latest
if test_endpoint "$BACKEND_URL/api/monitoring/reports/watchlist-dedup/latest" \
    "Watchlist Dedup Latest (Backend)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test watchlist dedup dated
if test_endpoint "$BACKEND_URL/api/monitoring/reports/watchlist-dedup/$TEST_DATE" \
    "Watchlist Dedup Dated (Backend)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test invalid date format
if test_endpoint "$BACKEND_URL/api/monitoring/reports/watchlist-consistency/invalid" \
    "Invalid Date Format (Backend)" 400; then
    ((PASSED++))
else
    ((FAILED++))
fi

echo ""
echo "📋 Testing HEAD Method Support"
echo "-------------------------------"

# Test HEAD method for latest
if test_endpoint_head "$BACKEND_URL/api/monitoring/reports/watchlist-consistency/latest" \
    "Watchlist Consistency Latest HEAD (Backend)"; then
    ((PASSED++))
else
    ((FAILED++))
fi

echo ""
echo "📋 Testing Nginx Rewrite Rules"
echo "-------------------------------"

# Test nginx rewrite for latest
if test_endpoint "$NGINX_URL/docs/monitoring/watchlist_consistency_report_latest.md" \
    "Watchlist Consistency Latest (Nginx)"; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test nginx rewrite for dated
if test_endpoint "$NGINX_URL/docs/monitoring/watchlist_consistency_report_${TEST_DATE}.md" \
    "Watchlist Consistency Dated (Nginx)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test nginx rewrite for dedup latest
if test_endpoint "$NGINX_URL/docs/monitoring/watchlist_dedup_report_latest.md" \
    "Watchlist Dedup Latest (Nginx)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test nginx rewrite for dedup dated
if test_endpoint "$NGINX_URL/docs/monitoring/watchlist_dedup_report_${TEST_DATE}.md" \
    "Watchlist Dedup Dated (Nginx)" 200 404; then
    ((PASSED++))
else
    ((FAILED++))
fi

echo ""
echo "📋 Testing Content Type"
echo "----------------------"

# Check content type for latest report
echo -n "Checking Content-Type for latest report... "
content_type=$(curl -s -I "$BACKEND_URL/api/monitoring/reports/watchlist-consistency/latest" | grep -i "content-type" | cut -d' ' -f2 | tr -d '\r\n')
if echo "$content_type" | grep -qi "text/markdown"; then
    echo -e "${GREEN}✅ PASS${NC} ($content_type)"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠️  WARNING${NC} (Expected text/markdown, got: $content_type)"
    ((FAILED++))
fi

echo ""
echo "============================"
echo "📊 Test Results"
echo "============================"
echo -e "${GREEN}Passed: $PASSED${NC}"
if [ $FAILED -gt 0 ]; then
    echo -e "${RED}Failed: $FAILED${NC}"
else
    echo -e "${GREEN}Failed: $FAILED${NC}"
fi
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Some tests failed${NC}"
    exit 1
fi







