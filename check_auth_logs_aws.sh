#!/bin/bash
# Script to check authentication logs on AWS server
# Run this on your AWS server: ./check_auth_logs_aws.sh

echo "================================================================================"
echo "🔍 CHECKING AUTHENTICATION LOGS AND CONFIGURATION"
echo "================================================================================"
echo ""

# Check environment variables
echo "1. ENVIRONMENT VARIABLES:"
echo "-------------------------"
docker compose exec backend env 2>/dev/null | grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" || echo "⚠️  Could not check environment variables (backend may not be running)"
echo ""

# Check recent authentication errors
echo "2. RECENT AUTHENTICATION ERRORS:"
echo "---------------------------------"
docker compose logs backend --tail 200 2>/dev/null | grep -A 20 "AUTHENTICATION FAILED" | tail -40 || echo "No recent authentication errors found"
echo ""

# Check SELL order creation attempts
echo "3. RECENT SELL ORDER CREATION ATTEMPTS:"
echo "--------------------------------------"
docker compose logs backend --tail 200 2>/dev/null | grep -A 15 "Creating automatic SELL order" | tail -30 || echo "No recent SELL order attempts found"
echo ""

# Check diagnostic logs
echo "4. DIAGNOSTIC LOGS (if CRYPTO_AUTH_DIAG=true):"
echo "-----------------------------------------------"
docker compose logs backend --tail 200 2>/dev/null | grep "CRYPTO_AUTH_DIAG" | tail -20 || echo "No diagnostic logs found (CRYPTO_AUTH_DIAG may not be enabled)"
echo ""

# Check MARGIN ORDER configuration
echo "5. MARGIN ORDER CONFIGURATION:"
echo "------------------------------"
docker compose logs backend --tail 200 2>/dev/null | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -10 || echo "No margin order logs found"
echo ""

# Check .env.aws file
echo "6. .env.aws CONFIGURATION:"
echo "-------------------------"
if [ -f .env.aws ]; then
    echo "File exists. Checking relevant variables:"
    grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" .env.aws || echo "Variables not found in .env.aws"
else
    echo "⚠️  .env.aws file not found"
fi
echo ""

# Check backend status
echo "7. BACKEND STATUS:"
echo "------------------"
docker compose ps backend 2>/dev/null || echo "⚠️  Could not check backend status"
echo ""

echo "================================================================================"
echo "📋 SUMMARY"
echo "================================================================================"
echo ""
echo "If you see 'AUTHENTICATION FAILED' errors above, check:"
echo "1. Is CRYPTO_SKIP_EXEC_INST=true set in .env.aws?"
echo "2. Has the backend been restarted after setting the variable?"
echo "3. Are the diagnostic logs showing signature generation details?"
echo ""
echo "To apply the fix:"
echo "  echo 'CRYPTO_SKIP_EXEC_INST=true' >> .env.aws"
echo "  echo 'CRYPTO_AUTH_DIAG=true' >> .env.aws"
echo "  docker compose restart backend"
echo ""

