#!/bin/bash
# Deploy fix for /docs/monitoring/watchlist_consistency_report_latest.md 404 error

set -e

echo "🔧 Deploying Docs Endpoint Fix"
echo "================================"
echo ""

SERVER="ubuntu@175.41.189.249"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "📦 Step 1: Syncing backend routes_monitoring.py..."
rsync_cmd \
  --exclude='venv/' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  ./backend/app/api/routes_monitoring.py \
  $SERVER:~/automated-trading-platform/backend/app/api/routes_monitoring.py

echo ""
echo "📝 Step 2: Syncing nginx configuration..."
rsync_cmd \
  ./nginx/dashboard.conf \
  $SERVER:~/automated-trading-platform/nginx/dashboard.conf

echo ""
echo "🔍 Step 3: Testing nginx configuration on server..."
ssh_cmd $SERVER 'sudo nginx -t'

echo ""
echo "🔄 Step 4: Reloading nginx..."
ssh_cmd $SERVER 'sudo systemctl reload nginx'

echo ""
echo "🔄 Step 5: Restarting backend service (if running as systemd service)..."
# Try to restart backend service, but don't fail if it doesn't exist
ssh_cmd $SERVER 'sudo systemctl restart trading-backend 2>/dev/null || sudo systemctl restart backend 2>/dev/null || echo "Backend service not found - you may need to restart manually"'

echo ""
echo "✅ Deployment complete!"
echo ""
echo "The following endpoints should now work:"
echo "  - https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md"
echo "  - https://dashboard.hilovivo.com/api/monitoring/reports/watchlist-consistency/latest"
echo ""
echo "To verify, test the endpoint:"
echo "  curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md"
echo ""





