#!/bin/bash
# Deploy Telegram Alerts Fix to AWS
# This script syncs the fix and restarts the market-updater-aws service

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Telegram Alerts Fix to AWS..."
echo ""
echo "Fix: Added explicit origin parameter to send_buy_signal() and send_sell_signal()"
echo "This ensures alerts are sent to Telegram by explicitly passing origin='AWS'"
echo ""

# Sync the changed backend file
echo "📦 Syncing signal_monitor.py..."
rsync_cmd \
  backend/app/services/signal_monitor.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/services/

# Also sync the diagnostic script
echo "📦 Syncing diagnose_telegram_alerts.py..."
rsync_cmd \
  backend/scripts/diagnose_telegram_alerts.py \
  $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/scripts/ 2>/dev/null || true

# Copy file into Docker container and restart
echo "🐳 Copying file into Docker container and restarting market-updater-aws..."
ssh_cmd $EC2_USER@$EC2_HOST << 'DEPLOY'
cd ~/automated-trading-platform || cd /home/ubuntu/crypto-2.0

# Find the market-updater-aws container name
MARKET_UPDATER_CONTAINER=$(docker ps --filter "name=market-updater-aws" --format "{{.Names}}" | head -1)

if [ -z "$MARKET_UPDATER_CONTAINER" ]; then
  echo "❌ Error: market-updater-aws container not found"
  echo "Available containers:"
  docker ps --format "{{.Names}}"
  exit 1
fi

echo "📋 Found market-updater-aws container: $MARKET_UPDATER_CONTAINER"

# Copy the file into the container
echo "📋 Copying signal_monitor.py into container..."
docker cp backend/app/services/signal_monitor.py $MARKET_UPDATER_CONTAINER:/app/app/services/signal_monitor.py

# Verify the import is present
echo "🔍 Verifying fix is present in container..."
docker exec $MARKET_UPDATER_CONTAINER grep -q "from app.core.runtime import get_runtime_origin" /app/app/services/signal_monitor.py && \
  echo "✅ Import statement found" || \
  echo "⚠️  Warning: Import statement not found"

docker exec $MARKET_UPDATER_CONTAINER grep -q "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py && \
  echo "✅ Origin parameter fix found" || \
  echo "⚠️  Warning: Origin parameter fix not found"

# Restart the market-updater-aws container
echo "🔄 Restarting market-updater-aws container..."
docker compose --profile aws restart market-updater-aws || docker restart $MARKET_UPDATER_CONTAINER

# Wait a moment for the service to restart
echo "⏳ Waiting for service to restart..."
sleep 5

# Check if market-updater-aws is running
if docker ps --filter "name=market-updater-aws" --format "{{.Status}}" | grep -q "Up"; then
  echo "✅ market-updater-aws restarted successfully"
else
  echo "⚠️  Warning: market-updater-aws container status unclear"
  docker ps --filter "name=market-updater" --format "table {{.Names}}\t{{.Status}}"
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Monitor logs: docker compose --profile aws logs -f market-updater-aws | grep TELEGRAM"
echo "2. Run diagnostic: docker compose --profile aws exec market-updater-aws python3 backend/scripts/diagnose_telegram_alerts.py"
echo "3. Wait for next alert and verify it's received in Telegram"
DEPLOY

echo ""
echo "✅ Fix deployed successfully!"
echo ""
echo "The Telegram alerts fix has been deployed."
echo "Alerts should now be sent to Telegram with explicit origin='AWS' parameter."




