#!/bin/bash
set -e

SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to backend/)
. "$(cd "$(dirname "$0")/.."; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")/.."; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying order history database system..."
echo ""

# Sync the new files
echo "📦 Syncing order history files..."
rsync_cmd \
  backend/app/models/order_history.py \
  backend/app/services/order_history_db.py \
  backend/app/api/routes_orders.py \
  $SERVER:~/crypto-2.0/backend/app/

echo "✅ Files synced"
