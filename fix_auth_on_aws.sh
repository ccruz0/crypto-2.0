#!/bin/bash
# Authentication fix script - Run this directly on AWS server
# Copy this file to AWS and run: bash fix_auth_on_aws.sh

set -e

echo "================================================================================"
echo "🔧 APPLYING AUTHENTICATION FIX"
echo "================================================================================"
echo ""

cd ~/automated-trading-platform || { echo "❌ Could not find automated-trading-platform directory"; exit 1; }

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
echo "4. Checking backend status..."

# Check if Docker is available and backend is running
if command -v docker &> /dev/null && docker ps 2>/dev/null | grep -q backend; then
    echo "   ✅ Docker is running, backend container found"
    echo "   Restarting backend..."
    docker compose restart backend
    echo "   ✅ Backend restarted"
    sleep 5
    echo ""
    echo "5. Checking logs..."
    docker compose logs backend --tail 50 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet (wait for next order)"
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "   ✅ Backend process found (uvicorn)"
    PID=$(pgrep -f "uvicorn app.main:app" | head -1)
    echo "   PID: $PID"
    echo ""
    echo "   ⚠️  Backend is running as a process (not Docker)"
    echo "   You need to restart it manually to apply the fix:"
    echo ""
    echo "   pkill -f 'uvicorn app.main:app'"
    echo "   cd ~/automated-trading-platform/backend"
    echo "   source venv/bin/activate  # if using venv"
    echo "   nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &"
    echo ""
elif pgrep -f "python.*main:app" > /dev/null; then
    echo "   ✅ Backend process found (python)"
    PID=$(pgrep -f "python.*main:app" | head -1)
    echo "   PID: $PID"
    echo ""
    echo "   ⚠️  Backend is running as a process (not Docker)"
    echo "   You need to restart it manually to apply the fix"
else
    echo "   ⚠️  No backend process found"
    echo "   Fix has been applied to .env.aws"
    echo "   Start your backend to apply the changes"
fi

echo ""
echo "================================================================================"
echo "✅ FIX APPLIED TO .env.aws"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "1. If using Docker: Backend has been restarted"
echo "2. If running as process: Restart your backend process (see commands above)"
echo "3. Monitor logs for next order creation"
echo "4. You should see: 'MARGIN ORDER CONFIGURED: leverage=X (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)'"
echo ""
echo "To check logs:"
echo "  - Docker: docker compose logs backend -f | grep -E 'AUTHENTICATION|order created'"
echo "  - Process: tail -f ~/automated-trading-platform/backend/backend.log | grep -E 'AUTHENTICATION|order created'"
echo ""

