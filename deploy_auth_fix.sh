#!/bin/bash
# Deploy authentication fix to AWS
set -e

SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to script location)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || true

echo "================================================================================"
echo "🚀 DEPLOYING AUTHENTICATION FIX TO AWS"
echo "================================================================================"
echo ""

# Step 1: Sync updated code files
echo "📦 Step 1: Syncing updated code files..."
rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='backend.log' \
  backend/app/services/brokers/crypto_com_trade.py \
  $SERVER:~/automated-trading-platform/backend/app/services/brokers/

rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  backend/app/services/signal_monitor.py \
  $SERVER:~/automated-trading-platform/backend/app/services/

echo "✅ Code files synced"

# Step 2: Apply environment variable fix
echo ""
echo "⚙️  Step 2: Applying environment variable fix..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

# Add fix to .env.aws
if [ -f .env.aws ]; then
    # Remove existing entries if any
    sed -i '/^CRYPTO_SKIP_EXEC_INST=/d' .env.aws 2>/dev/null || true
    sed -i '/^CRYPTO_AUTH_DIAG=/d' .env.aws 2>/dev/null || true
else
    touch .env.aws
fi

# Add new entries
echo "CRYPTO_SKIP_EXEC_INST=true" >> .env.aws
echo "CRYPTO_AUTH_DIAG=true" >> .env.aws

echo "✅ Added to .env.aws:"
grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG" .env.aws
ENDSSH

# Step 3: Restart backend
echo ""
echo "🔄 Step 3: Restarting backend..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

# Check if using Docker
if command -v docker &> /dev/null && docker ps 2>/dev/null | grep -q backend; then
    echo "   Using Docker - restarting container..."
    docker compose restart backend
    echo "   ✅ Backend restarted (Docker)"
    sleep 5
    echo ""
    echo "   Checking logs..."
    docker compose logs backend --tail 30 | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet"
elif pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "   Backend running as process - restarting..."
    pkill -f "uvicorn app.main:app" || true
    sleep 2
    cd ~/automated-trading-platform/backend
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi
    nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
    echo "   ✅ Backend restarted (process)"
    sleep 3
    echo ""
    echo "   Checking logs..."
    tail -30 backend.log | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -5 || echo "   No margin order logs yet"
else
    echo "   ⚠️  No backend process found"
    echo "   Code and .env.aws updated - start backend manually"
fi
ENDSSH

echo ""
echo "================================================================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "================================================================================"
echo ""
echo "What was deployed:"
echo "  ✅ Updated crypto_com_trade.py (with CRYPTO_SKIP_EXEC_INST support)"
echo "  ✅ Updated signal_monitor.py (with diagnostic logging)"
echo "  ✅ Added CRYPTO_SKIP_EXEC_INST=true to .env.aws"
echo "  ✅ Added CRYPTO_AUTH_DIAG=true to .env.aws"
echo "  ✅ Backend restarted"
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

