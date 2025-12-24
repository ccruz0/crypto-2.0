#!/bin/bash
# Deploy authentication fix - Run this directly on AWS server
# Copy this file to AWS and run: bash deploy_auth_fix_on_aws.sh

set -e

echo "================================================================================"
echo "🚀 DEPLOYING AUTHENTICATION FIX"
echo "================================================================================"
echo ""

cd ~/automated-trading-platform || { echo "❌ Could not find automated-trading-platform directory"; exit 1; }

# Step 1: Verify code files exist
echo "1. Verifying code files..."
if [ -f "backend/app/services/brokers/crypto_com_trade.py" ]; then
    echo "   ✅ crypto_com_trade.py found"
else
    echo "   ❌ crypto_com_trade.py not found - code may need to be synced"
fi

if [ -f "backend/app/services/signal_monitor.py" ]; then
    echo "   ✅ signal_monitor.py found"
else
    echo "   ❌ signal_monitor.py not found - code may need to be synced"
fi

# Step 2: Apply environment variable fix
echo ""
echo "2. Applying environment variable fix..."
if [ -f .env.aws ]; then
    # Remove existing entries if any
    sed -i '/^CRYPTO_SKIP_EXEC_INST=/d' .env.aws 2>/dev/null || true
    sed -i '/^CRYPTO_AUTH_DIAG=/d' .env.aws 2>/dev/null || true
    echo "   ✅ Updated existing .env.aws"
else
    touch .env.aws
    echo "   ✅ Created .env.aws"
fi

# Add new entries
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

echo "   ✅ Added CRYPTO_SKIP_EXEC_INST=true"
echo "   ✅ Added CRYPTO_AUTH_DIAG=true"

echo ""
echo "3. Verifying .env.aws..."
grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG" .env.aws

# Step 3: Restart backend
echo ""
echo "4. Restarting backend..."

# Check if using Docker
if command -v docker &> /dev/null && docker ps 2>/dev/null | grep -q backend; then
    echo "   ✅ Docker is running, backend container found"
    echo "   Restarting backend container..."
    docker compose restart backend
    echo "   ✅ Backend restarted (Docker)"
    sleep 5
    echo ""
    echo "5. Checking logs..."
    docker compose logs backend --tail 50 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet (wait for next order)"
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "   ✅ Backend process found (uvicorn)"
    PID=$(pgrep -f "uvicorn app.main:app" | head -1)
    echo "   Current PID: $PID"
    echo "   Restarting backend process..."
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    cd ~/automated-trading-platform/backend
    if [ -d "venv" ]; then
        source venv/bin/activate
        echo "   ✅ Activated virtual environment"
    fi
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    NEW_PID=$!
    echo "   ✅ Backend restarted (process), new PID: $NEW_PID"
    sleep 3
    echo ""
    echo "5. Checking logs..."
    tail -50 backend.log | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet (wait for next order)"
elif pgrep -f "python.*main:app" > /dev/null; then
    echo "   ✅ Backend process found (python)"
    PID=$(pgrep -f "python.*main:app" | head -1)
    echo "   Current PID: $PID"
    echo "   Restarting backend process..."
    pkill -f "python.*main:app" || true
    sleep 2
    cd ~/automated-trading-platform/backend
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    echo "   ✅ Backend restarted (process)"
else
    echo "   ⚠️  No backend process found"
    echo "   ✅ Fix has been applied to .env.aws"
    echo "   Start your backend to apply the changes"
fi

echo ""
echo "================================================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "================================================================================"
echo ""
echo "What was deployed:"
echo "  ✅ Added CRYPTO_SKIP_EXEC_INST=true to .env.aws"
echo "  ✅ Added CRYPTO_AUTH_DIAG=true to .env.aws"
echo "  ✅ Backend restarted (if running)"
echo ""
echo "Next steps:"
echo "  1. Monitor logs for next order creation"
echo "  2. You should see: 'MARGIN ORDER CONFIGURED: leverage=X (exec_inst skipped per CRYPTO_SKIP_EXEC_INST=true)'"
echo "  3. Orders should be created without authentication errors"
echo ""
echo "To check logs:"
echo "  - Docker: docker compose logs backend -f | grep -E 'AUTHENTICATION|order created'"
echo "  - Process: tail -f ~/automated-trading-platform/backend/backend.log | grep -E 'AUTHENTICATION|order created'"
echo ""

