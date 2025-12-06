#!/bin/bash

# ==========================================
# Deploy Local Changes to AWS
# ==========================================
# This script syncs your local changes and deploys to AWS

set -e

echo "========================================="
echo "🚀 Deploy to AWS"
echo "========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Configuration
REMOTE_HOST="hilovivo-aws"
REMOTE_USER="ubuntu"
PROJECT_DIR="~/automated-trading-platform"

# Check SSH connection
print_status "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 "$REMOTE_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    print_error "Cannot connect to $REMOTE_HOST"
    print_info "Make sure your SSH config has 'hilovivo-aws' alias configured"
    exit 1
fi

# Ask for confirmation
echo ""
print_warning "This will deploy your local changes to AWS production server."
read -p "Continue? (y/N): " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    print_warning "Deployment cancelled"
    exit 0
fi

# Step 1: Sync code (exclude large files and build artifacts)
print_status "Syncing code to AWS server..."
rsync -avz --progress \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    --exclude='*.tar.gz' \
    --exclude='postgres_data' \
    --exclude='aws_postgres_data' \
    --exclude='.env' \
    --exclude='.env.local' \
    --exclude='backend-aws.tar.gz' \
    --exclude='frontend-aws.tar.gz' \
    ./ "$REMOTE_HOST:$PROJECT_DIR/"

# Step 2: Build and deploy on remote server
print_status "Building and deploying on AWS..."
ssh "$REMOTE_HOST" << 'DEPLOY_SCRIPT'
cd ~/automated-trading-platform

echo "Building backend..."
docker compose build backend-aws

echo "Building frontend..."
docker compose build frontend-aws

echo "Stopping old containers..."
docker compose --profile aws down backend-aws frontend-aws 2>/dev/null || true

echo "Starting new containers..."
docker compose --profile aws up -d backend-aws frontend-aws

echo "Waiting for services to be healthy..."
sleep 20

echo "Checking service status..."
docker compose --profile aws ps backend-aws frontend-aws

echo ""
echo "Testing backend health..."
if curl -f http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "✅ Backend is healthy"
else
    echo "⚠️  Backend health check failed"
fi

echo ""
echo "✅ Deployment complete!"
DEPLOY_SCRIPT

echo ""
print_status "Deployment to AWS completed!"
echo ""
print_info "Check the deployment:"
echo "   Backend:  ssh $REMOTE_HOST 'curl http://localhost:8002/ping_fast'"
echo "   Frontend: ssh $REMOTE_HOST 'curl http://localhost:3000'"
echo "   Logs:     ssh $REMOTE_HOST 'cd $PROJECT_DIR && docker compose --profile aws logs -f'"
echo ""

