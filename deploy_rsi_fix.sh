#!/bin/bash
# Deploy RSI validation fix: sync code first, then rebuild container

set -e

echo "🚀 Deploying RSI validation fix..."
echo ""

# Load SSH helpers
if [ -f "scripts/ssh_key.sh" ]; then
  . scripts/ssh_key.sh 2>/dev/null || source scripts/ssh_key.sh
fi

SERVER="${EC2_HOST:-175.41.189.249}"
USER="${EC2_USER:-ubuntu}"

echo "📡 Step 1: Syncing code to server..."
rsync_cmd \
  --exclude='.git' \
  --exclude='node_modules' \
  --exclude='.next' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='venv' \
  --exclude='.env' \
  ./backend/app/services/trading_signals.py \
  $USER@$SERVER:~/automated-trading-platform/backend/app/services/trading_signals.py

echo ""
echo "✅ Code synced"
echo ""
echo "🔍 Step 2: Verifying code on server..."
ssh_cmd $USER@$SERVER << 'VERIFY'
cd ~/automated-trading-platform/backend/app/services
if grep -q "CRITICAL FIX: RSI validation" trading_signals.py; then
  echo "✅ Fix found in server code"
  grep -A 3 "CRITICAL FIX: RSI validation" trading_signals.py | head -5
else
  echo "❌ Fix NOT found in server code!"
  exit 1
fi
VERIFY

echo ""
echo "🐳 Step 3: Rebuilding and restarting backend container..."
ssh_cmd $USER@$SERVER << 'DEPLOY'
cd ~/automated-trading-platform

echo "🛑 Stopping backend..."
docker compose --profile aws stop backend-aws || true

echo "🔨 Rebuilding backend image with new code..."
docker compose --profile aws build --no-cache backend-aws

echo "🚀 Starting backend..."
docker compose --profile aws up -d backend-aws

echo "⏳ Waiting for backend to start..."
sleep 10

echo "📋 Checking backend status..."
docker compose --profile aws ps backend-aws

echo ""
echo "📝 Checking backend logs for RSI validation..."
docker compose --profile aws logs --tail=20 backend-aws | grep -i "rsi\|buy" || echo "No RSI logs yet"
DEPLOY

echo ""
echo "✅ Deployment complete!"
echo ""
echo "💡 The RSI validation fix should now be active."
echo "💡 Test with SUI_USDT - RSI=43.29 should show WAIT (not BUY) when threshold is 40."


