#!/bin/bash

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "Deploying all frontend files to AWS..."

# Copy frontend files to AWS
rsync_cmd \
  --exclude 'node_modules' \
  --exclude '.next' \
  frontend/ \
  $EC2_USER@$EC2_HOST:/home/ubuntu/automated-trading-platform/frontend/

# Copy files into the Docker container and restart
ssh_cmd $EC2_USER@$EC2_HOST << 'EOF'
cd /home/ubuntu/automated-trading-platform
# Find the correct container name
CONTAINER_NAME=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -n "$CONTAINER_NAME" ]; then
  docker cp frontend/src/app/page.tsx $CONTAINER_NAME:/app/src/app/page.tsx
  docker cp frontend/src/lib/api.ts $CONTAINER_NAME:/app/src/lib/api.ts
  docker-compose restart frontend
else
  echo "Frontend container not found"
fi
EOF

echo "Frontend files updated successfully!"

