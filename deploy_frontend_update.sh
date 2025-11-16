#!/bin/bash
# Script to update frontend with hot reload capability
# This allows faster development iterations without full rebuilds

set -e

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

EC2_HOST="${EC2_HOST:-175.41.189.249}"
EC2_USER="${EC2_USER:-ubuntu}"
PROJECT_DIR="automated-trading-platform"

echo "🚀 Updating frontend on AWS..."

# Step 1: Copy updated frontend files
echo "📦 Copying frontend files..."
# Use helper
rsync_cmd \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    ./frontend/ "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/frontend/"

# Step 2: Rebuild and restart frontend
echo "🔨 Rebuilding frontend..."
# Use helper
ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/automated-trading-platform

# Rebuild frontend image
echo "Building frontend image..."
docker compose -f docker-compose.yml build frontend-aws

# Restart frontend container
echo "Restarting frontend container..."
docker compose -f docker-compose.yml up -d frontend-aws

# Wait for health check
echo "Waiting for frontend to be healthy..."
sleep 10

# Check status
docker compose -f docker-compose.yml ps frontend-aws

echo "✅ Frontend update complete!"
DEPLOY_SCRIPT

echo "✅ Frontend updated successfully!"
