#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Verify Dashboard DNS and Connectivity
# ============================================
# This script verifies that dashboard.hilovivo.com
# is correctly configured and accessible after DNS update.
#
# Usage:
#   ./scripts/verify_dashboard_dns.sh
# ============================================

DOMAIN="dashboard.hilovivo.com"
EXPECTED_IP="47.130.143.159"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

PASS="${GREEN}✓${NC}"
FAIL="${RED}✗${NC}"
WARN="${YELLOW}⚠${NC}"

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Counters
PASSED=0
FAILED=0
WARNINGS=0

check() {
    local name="$1"
    local cmd="$2"
    
    echo -n "Checking $name... "
    if eval "$cmd" >/dev/null 2>&1; then
        echo -e "$PASS"
        ((PASSED++))
        return 0
    else
        echo -e "$FAIL"
        ((FAILED++))
        return 1
    fi
}

warn_check() {
    local name="$1"
    local cmd="$2"
    
    echo -n "Checking $name... "
    if eval "$cmd" >/dev/null 2>&1; then
        echo -e "$PASS"
        ((PASSED++))
        return 0
    else
        echo -e "$WARN"
        ((WARNINGS++))
        return 1
    fi
}

echo "=========================================="
echo "Dashboard DNS Verification"
echo "=========================================="
echo "Domain: $DOMAIN"
echo "Expected IP: $EXPECTED_IP"
echo ""

# 1. DNS Resolution
info "1. Checking DNS resolution..."
# Use Cloudflare DNS (1.1.1.1) which has faster propagation
ACTUAL_IP=$(dig @1.1.1.1 +short "$DOMAIN" A | head -1)
if [ -z "$ACTUAL_IP" ]; then
    # Fallback to default DNS
    ACTUAL_IP=$(dig +short "$DOMAIN" A | head -1)
fi
if [ "$ACTUAL_IP" = "$EXPECTED_IP" ]; then
    echo -e "  $PASS DNS resolves to $ACTUAL_IP"
    ((PASSED++))
else
    echo -e "  $FAIL DNS resolves to $ACTUAL_IP (expected $EXPECTED_IP)"
    ((FAILED++))
fi

# 2. HTTP Redirect
info "2. Checking HTTP redirect..."
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://$DOMAIN" 2>&1 || echo "000")
if [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
    echo -e "  $PASS HTTP returns $HTTP_CODE (redirect to HTTPS)"
    ((PASSED++))
else
    echo -e "  $FAIL HTTP returns $HTTP_CODE (expected 301/302)"
    ((FAILED++))
fi

# 3. HTTPS Access
info "3. Checking HTTPS access..."
HTTPS_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://$DOMAIN" 2>&1 || echo "000")
if [ "$HTTPS_CODE" = "200" ]; then
    echo -e "  $PASS HTTPS returns 200 OK"
    ((PASSED++))
else
    echo -e "  $FAIL HTTPS returns $HTTPS_CODE (expected 200)"
    ((FAILED++))
fi

# 4. SSL Certificate
info "4. Checking SSL certificate..."
if echo | openssl s_client -servername "$DOMAIN" -connect "$DOMAIN:443" 2>/dev/null | grep -q "Verify return code: 0"; then
    echo -e "  $PASS SSL certificate is valid"
    ((PASSED++))
else
    warn_check "SSL certificate validation" "echo | openssl s_client -servername \"$DOMAIN\" -connect \"$DOMAIN:443\" 2>/dev/null | grep -q 'Verify return code: 0'"
fi

# 5. Frontend Content
info "5. Checking frontend content..."
if curl -s --max-time 10 "https://$DOMAIN" | grep -q "Trading Dashboard"; then
    echo -e "  $PASS Frontend content loads"
    ((PASSED++))
else
    echo -e "  $FAIL Frontend content not found"
    ((FAILED++))
fi

# 6. API Health Check
info "6. Checking API health..."
API_HEALTH=$(curl -s --max-time 10 "https://$DOMAIN/api/health" 2>&1 || echo "error")
if echo "$API_HEALTH" | grep -q "status.*ok"; then
    echo -e "  $PASS API health check passes"
    ((PASSED++))
else
    echo -e "  $FAIL API health check failed: $API_HEALTH"
    ((FAILED++))
fi

# 7. API Dashboard Endpoint
info "7. Checking API dashboard endpoint..."
API_DASHBOARD=$(curl -s --max-time 10 "https://$DOMAIN/api/dashboard/state" 2>&1 | head -c 100)
if echo "$API_DASHBOARD" | grep -qE "(balances|portfolio|watchlist)"; then
    echo -e "  $PASS API dashboard endpoint responds"
    ((PASSED++))
else
    warn_check "API dashboard endpoint" "curl -s --max-time 10 \"https://$DOMAIN/api/dashboard/state\" | grep -qE '(balances|portfolio|watchlist)'"
fi

# 8. Server Direct Access
info "8. Checking server direct access..."
DIRECT_HTTP=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://$EXPECTED_IP" 2>&1 || echo "000")
if [ "$DIRECT_HTTP" = "301" ] || [ "$DIRECT_HTTP" = "302" ]; then
    echo -e "  $PASS Server responds directly via IP"
    ((PASSED++))
else
    echo -e "  $WARN Server direct access returns $DIRECT_HTTP"
    ((WARNINGS++))
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo -e "  $PASS Passed: $PASSED"
if [ $FAILED -gt 0 ]; then
    echo -e "  $FAIL Failed: $FAILED"
fi
if [ $WARNINGS -gt 0 ]; then
    echo -e "  $WARN Warnings: $WARNINGS"
fi
echo ""

if [ $FAILED -eq 0 ]; then
    info "All critical checks passed! Dashboard should be working."
    exit 0
else
    error "Some checks failed. Please review the output above."
    exit 1
fi

