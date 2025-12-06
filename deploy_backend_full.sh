#!/bin/bash
# Full backend deployment script

set -e

echo "🚀 Full Backend Deployment"
echo "=========================="
echo ""

SERVER="ubuntu@175.41.189.249"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "📦 Step 1: Syncing backend directory..."
rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.env' \
  ./backend/ \
  $SERVER:~/automated-trading-platform/backend/

echo ""
echo "📝 Step 2: Ensuring critical files exist on server..."
ssh_cmd $SERVER 'mkdir -p ~/automated-trading-platform/backend/app/utils'
ssh_cmd $SERVER 'mkdir -p ~/automated-trading-platform/backend/app/models'

echo ""
echo "🔧 Step 3: Installing dependencies (this may take a minute)..."
ssh_cmd $SERVER 'cd ~/automated-trading-platform/backend && source venv/bin/activate && pip install -q fastapi uvicorn requests pydantic pydantic-settings sqlalchemy'

echo ""
echo "✅ Deployment complete!"
echo ""
echo "To start the backend, run:"
echo "ssh -i '~/.ssh/id_rsa' $SERVER 'cd ~/automated-trading-platform/backend && source venv/bin/activate && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'"
echo ""
