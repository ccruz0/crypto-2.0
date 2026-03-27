#!/bin/bash
set -e

REMOTE_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/crypto-2.0"

. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying telegram_notifier fix to AWS..."
echo ""

scp_cmd backend/app/services/telegram_notifier.py $REMOTE_HOST:$REMOTE_PATH/backend/app/services/

echo "✅ File synced"

ssh_cmd $REMOTE_HOST << 'DEPLOY'
cd ~/automated-trading-platform
CONTAINER_NAME=$(docker ps --format '{{.Names}}' | grep -E 'automated-trading-platform-backend|backend-aws' | head -1)
if [ -z "$CONTAINER_NAME" ]; then
    echo "❌ Error: No backend container found"
    exit 1
fi
echo "📋 Found container: $CONTAINER_NAME"
docker cp backend/app/services/telegram_notifier.py $CONTAINER_NAME:/app/app/services/telegram_notifier.py
docker restart $CONTAINER_NAME
sleep 5
echo "✅ Container restarted"
DEPLOY

echo ""
echo "✅ Deployment complete!"
