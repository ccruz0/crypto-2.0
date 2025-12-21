#!/bin/bash
# Deploy market data fixes and check market-updater status
# Run this script when SSH connection to AWS is available

set -e

SERVER="ubuntu@175.41.189.249"
REMOTE_PATH="~/automated-trading-platform"

# Load SSH config
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Market Data Fixes and Checking Status"
echo "=================================================="
echo ""

echo "📦 Step 1: Pulling latest code..."
ssh_cmd $SERVER "cd $REMOTE_PATH && git pull"
echo "✅ Code pulled"
echo ""

echo "🔄 Step 2: Restarting backend service..."
ssh_cmd $SERVER "cd $REMOTE_PATH && docker-compose --profile aws restart backend-aws"
echo "✅ Backend restarted"
echo ""

echo "⏳ Step 3: Waiting for backend to start (10 seconds)..."
sleep 10
echo ""

echo "📊 Step 4: Checking market-updater-aws logs (last 100 lines)..."
echo "=================================================================="
ssh_cmd $SERVER "cd $REMOTE_PATH && docker-compose --profile aws logs market-updater-aws --tail=100"
echo ""

echo "🔍 Step 5: Checking if market-updater-aws is running..."
ssh_cmd $SERVER "cd $REMOTE_PATH && docker-compose --profile aws ps | grep market-updater"
echo ""

echo "✅ Deployment and status check complete!"
echo ""
echo "Look for these log patterns:"
echo "  ✅ '✅ Fetched {N} candles from Binance' - OHLCV fetch successful"
echo "  ✅ '✅ Indicators for {symbol}: RSI=...' - Real calculations"
echo "  ⚠️  '⚠️ Only {N} candles' - Insufficient data warning"
echo "  ⚠️  '⚠️ No OHLCV data' - Fetch failures"
echo "  ❌ 'Error calculating indicators' - Calculation errors"

