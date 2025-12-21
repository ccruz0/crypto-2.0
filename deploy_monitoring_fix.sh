#!/bin/bash
# Deploy monitoring endpoint fix to AWS

set -e

EC2_HOST="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying monitoring endpoint fix to AWS..."
echo ""

# Sync the fixed file
echo "📦 Syncing routes_monitoring.py..."
rsync_cmd backend/app/api/routes_monitoring.py $EC2_USER@$EC2_HOST:~/automated-trading-platform/backend/app/api/ 2>&1 | grep -v "error:" | grep -v "warning:" || true

echo ""
echo "🐳 Deploying to Docker container..."

# Deploy via SSH
ssh_cmd $EC2_USER@$EC2_HOST 'bash -s' << 'REMOTE_SCRIPT'
cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Find backend container
BACKEND=$(docker ps --filter "name=backend" --format "{{.Names}}" | head -1)

echo "Backend container: ${BACKEND:-NOT FOUND}"

# Copy file into container
if [ -n "$BACKEND" ]; then
  docker cp backend/app/api/routes_monitoring.py $BACKEND:/app/app/api/routes_monitoring.py
  echo "✅ File copied into container"
  
  # Restart container
  docker compose --profile aws restart backend-aws 2>/dev/null || docker restart $BACKEND
  echo "✅ Container restarted"
  
  sleep 5
  curl -f http://localhost:8002/api/monitoring/summary >/dev/null 2>&1 && echo "✅ Monitoring endpoint healthy" || echo "⚠️  Endpoint check failed"
else
  echo "⚠️  Backend container not found"
fi

echo "✅ Deployment complete!"
REMOTE_SCRIPT

echo ""
echo "✅ All done!"




