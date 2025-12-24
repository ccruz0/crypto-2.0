#!/bin/bash
# Script to check authentication logs on AWS server
# Run from local machine - will SSH into AWS and check logs

set -e

# Get server from deploy script pattern
SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to script location)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || true

AWS_SERVER="${AWS_SERVER:-$SERVER}"

echo "================================================================================"
echo "🔍 CHECKING AUTHENTICATION LOGS ON AWS SERVER"
echo "================================================================================"
echo "Server: $AWS_SERVER"
echo ""

# Check if we can connect
echo "1. Testing SSH connection..."
if ssh_cmd -o ConnectTimeout=5 "$AWS_SERVER" "echo 'Connected'" 2>/dev/null; then
    echo "✅ SSH connection successful"
else
    echo "❌ Cannot connect to AWS server"
    echo "   Please check:"
    echo "   - SSH key is configured"
    echo "   - Server IP is correct: $AWS_SERVER"
    echo "   - You have network access to the server"
    exit 1
fi

echo ""
echo "2. Checking environment variables in .env.aws..."
echo "------------------------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
if [ -f .env.aws ]; then
    echo "File exists. Checking relevant variables:"
    grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" .env.aws || echo "⚠️  Variables not found in .env.aws"
else
    echo "⚠️  .env.aws file not found"
fi
ENDSSH

echo ""
echo "3. Checking environment variables in running container..."
echo "---------------------------------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose exec backend env 2>/dev/null | grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" || echo "⚠️  Could not check (backend may not be running or docker not accessible)"
ENDSSH

echo ""
echo "4. Recent authentication errors..."
echo "----------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose logs backend --tail 300 2>/dev/null | grep -A 30 "AUTHENTICATION FAILED" | tail -50 || echo "No recent authentication errors found"
ENDSSH

echo ""
echo "5. Recent SELL order creation attempts..."
echo "-----------------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose logs backend --tail 300 2>/dev/null | grep -A 20 "Creating automatic SELL order" | tail -40 || echo "No recent SELL order attempts found"
ENDSSH

echo ""
echo "6. MARGIN ORDER configuration logs..."
echo "-------------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose logs backend --tail 200 2>/dev/null | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -10 || echo "No margin order logs found"
ENDSSH

echo ""
echo "7. Diagnostic logs (if CRYPTO_AUTH_DIAG=true)..."
echo "------------------------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose logs backend --tail 300 2>/dev/null | grep "CRYPTO_AUTH_DIAG" | tail -20 || echo "No diagnostic logs found (CRYPTO_AUTH_DIAG may not be enabled)"
ENDSSH

echo ""
echo "8. Backend container status..."
echo "------------------------------"
ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose ps backend 2>/dev/null || echo "⚠️  Could not check backend status"
ENDSSH

echo ""
echo "================================================================================"
echo "📋 SUMMARY"
echo "================================================================================"
echo ""
echo "If you see 'AUTHENTICATION FAILED' errors:"
echo "1. Check if CRYPTO_SKIP_EXEC_INST=true is in .env.aws"
echo "2. Verify backend was restarted after setting the variable"
echo "3. Check if logs show 'exec_inst skipped' message"
echo ""
echo "To apply the fix, run:"
echo "  ./apply_fix_on_aws.sh"
echo ""

