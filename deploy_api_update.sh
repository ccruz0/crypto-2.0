#!/bin/bash

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "Deploying api.ts update to AWS..."

# Copy the updated api.ts file to AWS
rsync_cmd \
  frontend/src/lib/api.ts \
  $EC2_USER@$EC2_HOST:/home/ubuntu/automated-trading-platform/frontend/src/lib/api.ts

# Copy the file into the Docker container
ssh_cmd $EC2_USER@$EC2_HOST << 'EOF'
cd /home/ubuntu/automated-trading-platform
# Find the correct container name
CONTAINER_NAME=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -n "$CONTAINER_NAME" ]; then
  docker cp frontend/src/lib/api.ts $CONTAINER_NAME:/app/src/lib/api.ts
  docker-compose restart frontend
else
  echo "Frontend container not found"
fi
EOF

echo "API.ts updated successfully!"

