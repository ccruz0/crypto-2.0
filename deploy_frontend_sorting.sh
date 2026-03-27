#!/bin/bash
set -e

# Configuration
EC2_HOST_PRIMARY="47.130.143.159"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh
PROJECT_DIR="automated-trading-platform"

# Try to determine which host to use
EC2_HOST=""
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    echo "✅ Using primary host: $EC2_HOST"
elif ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    echo "✅ Using alternative host: $EC2_HOST"
else
    echo "❌ Cannot connect to either host"
    exit 1
fi

echo "🚀 Deploying frontend sorting feature to AWS..."

# Step 1: Copy frontend files
echo "📦 Copying frontend files..."
rsync_cmd \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    ./frontend/ "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/frontend/"

# Step 2: Rebuild and restart frontend
echo "🔨 Rebuilding and restarting frontend..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/crypto-2.0

# Rebuild frontend
echo "Building frontend image..."
docker compose -f docker-compose.yml build frontend-aws || docker compose -f docker-compose.yml build frontend

# Restart frontend container
echo "Restarting frontend container..."
docker compose -f docker-compose.yml up -d frontend-aws || docker compose -f docker-compose.yml up -d frontend

# Wait for health check
echo "Waiting for frontend to be healthy..."
sleep 15

# Check status
docker compose -f docker-compose.yml ps | grep frontend

echo "✅ Frontend deployment complete!"
DEPLOY_SCRIPT

echo "✅ Frontend sorting feature deployed successfully!"
