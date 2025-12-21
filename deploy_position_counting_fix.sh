#!/bin/bash
# Deploy position counting fix to AWS and restart backend

set -e

SERVER="ubuntu@175.41.189.249"
# Unified SSH (relative to project root)
. "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh" 2>/dev/null || source "$(cd "$(dirname "$0")"; pwd)/scripts/ssh_key.sh"

echo "🚀 Deploying position counting fix to AWS..."
echo ""

# Sync the specific file that was fixed
echo "📦 Syncing order_position_service.py..."
rsync_cmd \
  backend/app/services/order_position_service.py \
  $SERVER:~/automated-trading-platform/backend/app/services/order_position_service.py

echo ""
echo "🔄 Restarting backend container..."
ssh_cmd $SERVER << 'ENDSSH'
cd ~/automated-trading-platform

# Restart the backend-aws container
if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
    echo "🔄 Restarting backend-aws container..."
    docker compose --profile aws restart backend-aws
    echo "✅ Backend container restarted"
    
    # Wait a bit and check status
    sleep 5
    echo ""
    echo "📊 Backend status:"
    docker compose --profile aws ps backend-aws
    
    echo ""
    echo "📋 Recent logs (checking for position counting):"
    docker compose --profile aws logs --tail=30 backend-aws | grep -i "position\|AAVE" | tail -10 || echo "No position logs found yet"
else
    echo "⚠️  Backend-aws container not found or not running"
    docker compose --profile aws ps
fi
ENDSSH

echo ""
echo "✅ Deployment complete!"
echo ""
echo "The position counting fix has been deployed. The system should now correctly count"
echo "AAVE positions based on net quantity instead of individual orders."
echo ""
echo "You can now try the AAVE test order again."







