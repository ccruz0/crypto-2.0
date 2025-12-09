#!/bin/bash
set -e

# Deploy signal throttle logging improvements to AWS
# This script syncs the updated signal_monitor.py and restarts the backend container

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"

# Unified SSH
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying signal throttle logging fix to AWS..."
echo ""

# Step 1: Sync the updated file
echo "📦 Syncing signal_monitor.py..."
scp_cmd \
  backend/app/services/signal_monitor.py \
  $REMOTE_HOST:$REMOTE_PATH/backend/app/services/signal_monitor.py

echo "✅ File synced"

# Step 2: Copy file into Docker container and restart
echo ""
echo "🐳 Updating Docker container..."
ssh_cmd $REMOTE_HOST << 'DEPLOY'
cd ~/automated-trading-platform

# Find backend container name
CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep -E 'automated-trading-platform-backend|backend-aws' | head -1)

if [ -z "$CONTAINER_NAME" ]; then
    echo "❌ Error: No backend container found"
    docker ps --format 'table {{.Names}}\t{{.Status}}'
    exit 1
fi

echo "📋 Found container: $CONTAINER_NAME"

# Copy file into container
echo "📤 Copying signal_monitor.py into container..."
docker cp backend/app/services/signal_monitor.py $CONTAINER_NAME:/app/app/services/signal_monitor.py

# Restart container to apply changes
echo "🔄 Restarting container..."
docker restart $CONTAINER_NAME

echo "⏳ Waiting for container to be ready..."
sleep 5

# Verify container is running
if docker ps | grep -q $CONTAINER_NAME; then
    echo "✅ Container restarted successfully"
    echo ""
    echo "📊 Container status:"
    docker ps --filter name=$CONTAINER_NAME --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
else
    echo "❌ Error: Container is not running after restart"
    exit 1
fi

echo ""
echo "✅ Deployment complete!"
DEPLOY

echo ""
echo "🎉 Signal throttle logging fix deployed successfully!"
echo ""
echo "💡 Next steps:"
echo "   1. Monitor logs: bash scripts/aws_backend_logs.sh -f | grep -E '(throttled|Recording signal)'"
echo "   2. Check dashboard for new throttle events"
echo "   3. Verify that throttle messages are now visible in logs"
