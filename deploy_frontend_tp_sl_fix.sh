#!/bin/bash

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying frontend TP/SL Value fix to AWS..."

# Copy frontend files to AWS
echo "📦 Copying frontend files..."
rsync_cmd \
  --exclude 'node_modules' \
  --exclude '.next' \
  frontend/ \
  $EC2_USER@$EC2_HOST:/home/ubuntu/automated-trading-platform/frontend/

# Rebuild and restart on server
echo "🔨 Rebuilding Docker image and restarting container..."
ssh_cmd $EC2_USER@$EC2_HOST << 'EOF'
cd /home/ubuntu/automated-trading-platform
echo "Building frontend Docker image..."
docker-compose build --no-cache frontend-aws
echo "Stopping and removing old container..."
docker-compose stop frontend-aws
docker-compose rm -f frontend-aws
echo "Starting new container..."
docker-compose up -d frontend-aws
echo "Waiting for container to be healthy..."
sleep 10
docker ps --filter "name=frontend-aws" --format "table {{.Names}}\t{{.Status}}"
EOF

echo "✅ Frontend deployment complete!"
