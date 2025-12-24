#!/bin/bash
# Apply authentication fix directly on AWS server
# This script SSHs into AWS and runs commands directly (no Docker needed)

set -e

# Get server from deploy script pattern
SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to script location)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || true

echo "================================================================================"
echo "🔧 APPLYING AUTHENTICATION FIX ON AWS SERVER (Direct)"
echo "================================================================================"
echo "Server: $SERVER"
echo ""

# Apply fix directly on AWS
ssh_cmd "$SERVER" << 'ENDSSH'
cd ~/automated-trading-platform

echo "1. Checking current .env.aws..."
if [ -f .env.aws ]; then
    echo "   ✅ File exists"
    echo "   Current CRYPTO_SKIP_EXEC_INST setting:"
    grep CRYPTO_SKIP_EXEC_INST .env.aws || echo "   ⚠️  Not set"
else
    echo "   ⚠️  File does not exist, will create it"
    touch .env.aws
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
echo "   Contents:"
grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG" .env.aws

echo ""
echo "4. Checking if backend is running in Docker..."
if command -v docker &> /dev/null && docker ps | grep -q backend; then
    echo "   ✅ Docker is running, restarting backend..."
    docker compose restart backend
    echo "   ✅ Backend restarted"
    sleep 5
    echo ""
    echo "5. Checking logs..."
    docker compose logs backend --tail 50 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet (wait for next order)"
else
    echo "   ⚠️  Docker not running or backend not in Docker"
    echo "   ✅ Fix applied to .env.aws - restart backend when Docker is available"
fi

echo ""
echo "6. Checking if backend is running as a process..."
if pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "   ✅ Backend process found (uvicorn)"
    echo "   ⚠️  You may need to restart the backend process manually"
    echo "   Run: pkill -f 'uvicorn app.main:app' && cd ~/automated-trading-platform/backend && nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &"
elif pgrep -f "python.*main:app" > /dev/null; then
    echo "   ✅ Backend process found (python)"
    echo "   ⚠️  You may need to restart the backend process manually"
else
    echo "   ⚠️  No backend process found"
fi

echo ""
echo "================================================================================"
echo "✅ FIX APPLIED TO .env.aws"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "1. If using Docker: docker compose restart backend"
echo "2. If running directly: Restart your backend process"
echo "3. Monitor logs for next order creation"
echo "4. You should see: 'MARGIN ORDER CONFIGURED: leverage=X (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)'"
ENDSSH

echo ""
echo "================================================================================"
echo "✅ FIX APPLIED SUCCESSFULLY"
echo "================================================================================"
echo ""
echo "The fix has been applied to .env.aws on the AWS server."
echo "Restart your backend (Docker or process) to apply the changes."
echo ""

