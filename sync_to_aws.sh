#!/bin/bash

# AWS Sync and Deploy Script
# This script synchronizes the local development environment with AWS

set -e

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh
PROJECT_DIR="automated-trading-platform"
AWS_PROFILE="aws"

echo "========================================="
echo "AWS Sync and Deploy Script"
echo "========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check SSH connection
print_status "Testing SSH connection to AWS..."
ssh_cmd "$EC2_USER@$EC2_HOST" "echo 'SSH connection successful'" || {
    print_error "Cannot connect to AWS instance"
    exit 1
}

# Step 1: Build and tag Docker images locally
print_status "Building Docker images locally..."
docker compose build --no-cache

# Tag images for AWS
docker tag automated-trading-platform-backend:latest automated-trading-platform-backend:aws
docker tag automated-trading-platform-frontend:latest automated-trading-platform-frontend:aws

# Step 2: Save Docker images to tar files
print_status "Saving Docker images..."
docker save automated-trading-platform-backend:aws | gzip > backend-aws.tar.gz
docker save automated-trading-platform-frontend:aws | gzip > frontend-aws.tar.gz

# Step 3: Sync project files to AWS
print_status "Syncing project files to AWS..."
rsync_cmd \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.tar.gz' \
    --exclude='postgres_data' \
    --exclude='aws_postgres_data' \
    ./ "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/"

# Step 4: Copy Docker images to AWS
print_status "Copying Docker images to AWS..."
scp_cmd backend-aws.tar.gz "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/"
scp_cmd frontend-aws.tar.gz "$EC2_USER@$EC2_HOST:~/$PROJECT_DIR/"

# Step 5: Deploy on AWS
print_status "Deploying on AWS..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'DEPLOY_SCRIPT'
cd ~/automated-trading-platform

# Load Docker images
echo "Loading Docker images..."
docker load < backend-aws.tar.gz
docker load < frontend-aws.tar.gz

# Stop existing containers
echo "Stopping existing containers..."
docker compose --profile aws down || true

# Clean up old images
echo "Cleaning up old images..."
docker image prune -f || true

# Start services with AWS profile
echo "Starting services with AWS profile..."
docker compose --profile aws up -d

# Wait for services to be healthy
echo "Waiting for services to be healthy..."
sleep 30

# Check service status
echo "Checking service status..."
docker compose --profile aws ps

# Test backend health
echo "Testing backend health..."
curl -f http://localhost:8000/api/health || echo "Backend health check failed"

# Clean up tar files
rm -f backend-aws.tar.gz frontend-aws.tar.gz

echo "Deployment complete!"
DEPLOY_SCRIPT

# Step 6: Clean up local tar files
print_status "Cleaning up local files..."
rm -f backend-aws.tar.gz frontend-aws.tar.gz

# Step 7: Test AWS deployment
print_status "Testing AWS deployment..."
sleep 10

# Test backend
if curl -f --connect-timeout 10 "http://$EC2_HOST:8000/api/health" > /dev/null 2>&1; then
    print_status "✅ AWS Backend is healthy"
else
    print_warning "⚠️  AWS Backend health check failed"
fi

# Test frontend
if curl -f --connect-timeout 10 "http://$EC2_HOST:3000" > /dev/null 2>&1; then
    print_status "✅ AWS Frontend is accessible"
else
    print_warning "⚠️  AWS Frontend is not accessible"
fi

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""
echo "Your application is now running on AWS:"
echo "  Backend:  http://$EC2_HOST:8000"
echo "  Frontend: http://$EC2_HOST:3000"
echo ""
echo "Local development environment:"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
echo "The system will automatically failover between local and AWS based on availability."
