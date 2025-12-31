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

# Rebuild and restart frontend-aws container
ssh_cmd $EC2_USER@$EC2_HOST << 'EOF'
cd /home/ubuntu/automated-trading-platform
echo "Rebuilding frontend-aws container..."
docker compose --profile aws build frontend-aws
echo "Restarting frontend-aws container..."
docker compose --profile aws up -d frontend-aws
echo "Waiting for container to be healthy..."
sleep 10
docker compose --profile aws ps frontend-aws
EOF

echo "Frontend files updated successfully!"

