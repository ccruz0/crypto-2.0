#!/bin/bash
# Script to apply authentication fix on AWS server
# Run from local machine - will SSH into AWS and apply the fix

set -e

# Get server from deploy script pattern
SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to script location)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || true

AWS_SERVER="${AWS_SERVER:-$SERVER}"

echo "================================================================================"
echo "🔧 APPLYING AUTHENTICATION FIX ON AWS SERVER"
echo "================================================================================"
echo "Server: $AWS_SERVER"
echo ""

# Check if we can connect
echo "Testing SSH connection..."
if ssh_cmd -o ConnectTimeout=5 "$AWS_SERVER" "echo 'Connected'" 2>/dev/null; then
    echo "✅ SSH connection successful"
else
    echo "❌ Cannot connect to AWS server"
    echo "   Please check SSH configuration"
    exit 1
fi

echo ""
echo "Applying fix..."
echo ""

ssh_cmd "$AWS_SERVER" << 'ENDSSH'
cd ~/automated-trading-platform

echo "1. Checking current .env.aws..."
if [ -f .env.aws ]; then
    echo "   File exists"
    echo "   Current CRYPTO_SKIP_EXEC_INST setting:"
    grep CRYPTO_SKIP_EXEC_INST .env.aws || echo "   Not set"
else
    echo "   File does not exist, will create it"
fi

echo ""
echo "2. Adding fix to .env.aws..."

# Remove existing entries if any
sed -i '/^CRYPTO_SKIP_EXEC_INST=/d' .env.aws 2>/dev/null || true
sed -i '/^CRYPTO_AUTH_DIAG=/d' .env.aws 2>/dev/null || true

# Add new entries
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

echo "   ✅ Added CRYPTO_SKIP_EXEC_INST=true"
echo "   ✅ Added CRYPTO_AUTH_DIAG=true"

echo ""
echo "3. Verifying .env.aws..."
grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG" .env.aws

echo ""
echo "4. Restarting backend..."
docker compose restart backend

echo ""
echo "5. Waiting for backend to start..."
sleep 5

echo ""
echo "6. Checking if fix is applied..."
docker compose logs backend --tail 50 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet (wait for next order)"

echo ""
echo "✅ Fix applied! Backend restarted."
echo ""
echo "Next steps:"
echo "- Wait for next SELL signal or trigger test alert"
echo "- Check logs: docker compose logs backend -f | grep -E 'AUTHENTICATION|order created'"
echo "- You should see: 'MARGIN ORDER CONFIGURED: leverage=X (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)'"
ENDSSH

echo ""
echo "================================================================================"
echo "✅ FIX APPLIED SUCCESSFULLY"
echo "================================================================================"
echo ""
echo "The fix has been applied on the AWS server."
echo "Monitor the logs for the next order creation attempt."
echo ""

