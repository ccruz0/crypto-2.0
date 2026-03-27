#!/bin/bash
# Quick script to restart backend after RSI validation fix

set -e

echo "🔄 Restarting backend to apply RSI validation fix..."
echo ""

# Check if we have SSH access configured
if [ -f "scripts/ssh_key.sh" ]; then
  . scripts/ssh_key.sh 2>/dev/null || source scripts/ssh_key.sh
fi

# Try to restart backend on AWS
SERVER="${EC2_HOST:-175.41.189.249}"
USER="${EC2_USER:-ubuntu}"

echo "📡 Connecting to $USER@$SERVER..."
echo ""

# Restart backend service
if command -v ssh_cmd &> /dev/null; then
  ssh_cmd $USER@$SERVER << 'ENDSSH'
cd ~/crypto-2.0

echo "🛑 Stopping backend..."
docker compose --profile aws stop backend-aws || pkill -f "uvicorn app.main:app" || true

echo "⏳ Waiting 3 seconds..."
sleep 3

echo "🚀 Starting backend..."
docker compose --profile aws up -d --build backend-aws || {
  echo "⚠️ Docker compose failed, trying direct restart..."
  cd backend
  source venv/bin/activate 2>/dev/null || true
  nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
}

echo "⏳ Waiting for backend to start..."
sleep 5

echo "✅ Backend restarted"
echo ""
echo "📋 Checking backend status..."
docker compose --profile aws ps backend-aws || ps aux | grep uvicorn | grep -v grep || echo "⚠️ Backend process not found"

ENDSSH
else
  echo "⚠️ SSH helper not found. Please run manually:"
  echo ""
  echo "ssh $USER@$SERVER 'cd ~/crypto-2.0 && docker compose --profile aws restart backend-aws'"
  echo ""
  echo "Or if using direct Python:"
  echo "ssh $USER@$SERVER 'cd ~/crypto-2.0/backend && pkill -f uvicorn && source venv/bin/activate && nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &'"
fi

echo ""
echo "✅ Restart script completed"
echo ""
echo "💡 The RSI validation fix should now be active."
echo "💡 SUI_USDT with RSI=47.93 should now show WAIT (not BUY) when threshold is 40."







