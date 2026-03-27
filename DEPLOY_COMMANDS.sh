#!/bin/bash
# Copy-paste these commands on your AWS server to deploy the Telegram alerts fix

echo "🚀 Deploying Telegram Alerts Fix"
echo "================================="
echo ""

# Navigate to project
cd /home/ubuntu/crypto-2.0

# Fix git ownership (if needed)
export HOME=/home/ubuntu
git config --global --add safe.directory /home/ubuntu/crypto-2.0 2>/dev/null || true

# Pull latest code
echo "📥 Pulling latest code..."
git pull origin main || echo "⚠️ Git pull failed or already up to date"

# Find container
echo "🔍 Finding market-updater-aws container..."
CONTAINER=$(docker ps --filter "name=market-updater-aws" --format "{{.Names}}" | head -1)

if [ -z "$CONTAINER" ]; then
    echo "❌ Container not found. Available containers:"
    docker ps --format "{{.Names}}"
    exit 1
fi

echo "📋 Found container: $CONTAINER"

# Copy file into container
echo "📋 Copying signal_monitor.py into container..."
docker cp backend/app/services/signal_monitor.py $CONTAINER:/app/app/services/signal_monitor.py

# Verify fix
echo "🔍 Verifying fix..."
if docker exec $CONTAINER grep -q "alert_origin = get_runtime_origin()" /app/app/services/signal_monitor.py; then
    echo "✅ Fix verified in container"
else
    echo "❌ Fix not found in container"
    exit 1
fi

# Restart service
echo "🔄 Restarting market-updater-aws service..."
docker compose --profile aws restart market-updater-aws || docker restart $CONTAINER

# Wait and check status
echo "⏳ Waiting for service to restart..."
sleep 5

echo "🔍 Service status:"
docker ps --filter "name=market-updater-aws" --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "Next steps:"
echo "1. Monitor logs: docker compose --profile aws logs -f market-updater-aws | grep TELEGRAM"
echo "2. Wait for next alert and verify it's received in Telegram"




