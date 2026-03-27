#!/bin/bash
# Deploy market data enrichment fix
# This script syncs the routes_dashboard.py file and restarts the backend

set -e

echo "🚀 Deploying Market Data Enrichment Fix"
echo "========================================"
echo ""

SERVER="ubuntu@175.41.189.249"
REMOTE_PATH="~/crypto-2.0"

# Load SSH config
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "📦 Step 1: Syncing routes_dashboard.py..."
echo "   File: backend/app/api/routes_dashboard.py"

rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  backend/app/api/routes_dashboard.py \
  $SERVER:$REMOTE_PATH/backend/app/api/routes_dashboard.py

if [ $? -eq 0 ]; then
    echo "✅ File synced successfully"
else
    echo "❌ Sync failed. Trying alternative method..."
    exit 1
fi

echo ""
echo "🔄 Step 2: Restarting backend service..."

ssh_cmd $SERVER "cd $REMOTE_PATH && docker-compose --profile aws restart backend-aws"

if [ $? -eq 0 ]; then
    echo "✅ Backend restarted successfully"
else
    echo "⚠️  Restart command completed with warnings"
fi

echo ""
echo "📊 Step 3: Waiting for backend to be ready (10 seconds)..."
sleep 10

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Verification:"
echo "  - Check dashboard: https://dashboard.hilovivo.com"
echo "  - Run diagnostic: python3 check_market_data_via_api.py"
echo ""




