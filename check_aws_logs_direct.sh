#!/bin/bash
# Check authentication logs directly on AWS server
# This script SSHs into AWS and checks logs directly (no Docker needed)

set -e

# Get server from deploy script pattern
SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to script location)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || true

echo "================================================================================"
echo "🔍 CHECKING AUTHENTICATION LOGS ON AWS SERVER (Direct)"
echo "================================================================================"
echo "Server: $SERVER"
echo ""

ssh_cmd "$SERVER" << 'ENDSSH'
cd ~/automated-trading-platform

echo "1. Checking .env.aws file..."
echo "---------------------------"
if [ -f .env.aws ]; then
    echo "✅ File exists"
    echo "Relevant variables:"
    grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" .env.aws || echo "⚠️  Variables not found"
else
    echo "⚠️  .env.aws file not found"
fi

echo ""
echo "2. Checking if Docker is running..."
echo "-----------------------------------"
if command -v docker &> /dev/null; then
    if docker ps | grep -q backend; then
        echo "✅ Docker is running, backend container found"
        echo ""
        echo "3. Environment variables in container..."
        echo "----------------------------------------"
        docker compose exec backend env 2>/dev/null | grep -E "CRYPTO_SKIP_EXEC_INST|CRYPTO_AUTH_DIAG|USE_CRYPTO_PROXY|LIVE_TRADING|EXCHANGE_CUSTOM" || echo "⚠️  Could not check"
        echo ""
        echo "4. Recent authentication errors (Docker logs)..."
        echo "-----------------------------------------------"
        docker compose logs backend --tail 300 2>/dev/null | grep -A 30 "AUTHENTICATION FAILED" | tail -50 || echo "No recent authentication errors found"
        echo ""
        echo "5. Recent SELL order attempts (Docker logs)..."
        echo "---------------------------------------------"
        docker compose logs backend --tail 300 2>/dev/null | grep -A 20 "Creating automatic SELL order" | tail -40 || echo "No recent SELL order attempts found"
        echo ""
        echo "6. MARGIN ORDER configuration (Docker logs)..."
        echo "---------------------------------------------"
        docker compose logs backend --tail 200 2>/dev/null | grep -E "MARGIN ORDER CONFIGURED|exec_inst" | tail -10 || echo "No margin order logs found"
    else
        echo "⚠️  Docker is installed but backend container not running"
    fi
else
    echo "⚠️  Docker not installed or not in PATH"
fi

echo ""
echo "7. Checking backend process (if not in Docker)..."
echo "------------------------------------------------"
if pgrep -f "uvicorn app.main:app" > /dev/null; then
    echo "✅ Backend process found (uvicorn)"
    PID=$(pgrep -f "uvicorn app.main:app" | head -1)
    echo "   PID: $PID"
    echo "   Working directory:"
    pwdx $PID 2>/dev/null || echo "   Could not determine working directory"
    echo ""
    echo "8. Checking backend log file..."
    if [ -f ~/automated-trading-platform/backend/backend.log ]; then
        echo "   ✅ Log file found: backend/backend.log"
        echo "   Recent authentication errors:"
        tail -500 ~/automated-trading-platform/backend/backend.log | grep -A 20 "AUTHENTICATION FAILED" | tail -40 || echo "   No authentication errors in log file"
    else
        echo "   ⚠️  Log file not found"
    fi
elif pgrep -f "python.*main:app" > /dev/null; then
    echo "✅ Backend process found (python)"
    PID=$(pgrep -f "python.*main:app" | head -1)
    echo "   PID: $PID"
else
    echo "⚠️  No backend process found"
fi

echo ""
echo "================================================================================"
echo "📋 SUMMARY"
echo "================================================================================"
echo ""
echo "If you see 'AUTHENTICATION FAILED' errors:"
echo "1. Verify CRYPTO_SKIP_EXEC_INST=true is in .env.aws"
echo "2. Restart backend (Docker or process)"
echo "3. Check logs show 'exec_inst skipped' message"
echo ""
ENDSSH

echo ""
echo "✅ Check complete!"
echo ""

