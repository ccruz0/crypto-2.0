#!/bin/bash
set -e

SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to backend/)
. "$(cd "$(dirname "$0")/.."; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")/.."; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying backend to AWS..."
echo ""

# Sync backend files
echo "📦 Syncing backend files..."
rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  ./backend/ \
  $SERVER:~/automated-trading-platform/backend/

echo ""
echo "⚙️  Setting up environment and starting backend..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform/backend

# Create .env file with AWS proxy configuration
cat > .env << 'ENVFILE'
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://127.0.0.1:9000
CRYPTO_PROXY_TOKEN=CRYPTO_PROXY_SECURE_TOKEN_2024
LIVE_TRADING=true
ENVFILE

echo "✅ Environment configured"

# Install dependencies if needed
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --quiet fastapi uvicorn requests pydantic pydantic-settings sqlalchemy psycopg2-binary python-dotenv python-multipart
else
    echo "📦 Virtual environment already exists"
    source venv/bin/activate
    pip install --quiet -r requirements.txt
fi

# Stop any existing backend
echo "🛑 Stopping existing backend..."
pkill -f "uvicorn app.main:app" || true
sleep 2

# Start backend
echo "🚀 Starting backend..."
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &

sleep 3
echo "✅ Backend started"
tail -20 backend.log
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Backend should be running at: http://175.41.189.249:8000"
