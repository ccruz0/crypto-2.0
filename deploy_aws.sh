#!/usr/bin/env bash
set -euo pipefail

# ============================================
# AWS Deployment Script
# ============================================
# This script synchronizes necessary files to the AWS server and deploys
# the services using the 'aws' Docker Compose profile.
#
# Usage:
#   ./deploy_aws.sh
#
# What it does:
#   1. Checks that docker-compose.yml and .env exist locally
#   2. Synchronizes docker-compose.yml, .env, docker/, frontend/, and backend/ folders to the server
#   3. Stops existing services, pulls latest images, and starts services with 'aws' profile
#   4. Shows the status of running services
#
# Requirements:
#   - SSH key must be at ~/.ssh/id_rsa
#   - Server must be accessible at ubuntu@47.130.143.159 (or override HOST env var)
#   - .env file must exist in the project root (not modified by this script)
#   - Scripts are non-interactive; id_rsa must not prompt for passphrase
#
# To make executable:
#   chmod +x deploy_aws.sh
#
# Ensure ~/.ssh/id_rsa exists and is authorized on server
# ============================================

# Configuration
HOST="${HOST:-ubuntu@47.130.143.159}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/automated-trading-platform}"
# Load unified SSH helper
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Step 1: Check that docker-compose.yml exists locally
info "Checking local files..."
if [ ! -f "docker-compose.yml" ]; then
    error "docker-compose.yml not found in current directory"
    exit 1
fi

# Step 2: Check that .env exists locally (but don't read it)
if [ ! -f ".env" ]; then
    error ".env file not found in current directory"
    exit 1
fi

info "Local files check passed ✓"

# Step 4: Test SSH connection
info "Testing SSH connection..."
if ! ssh_cmd "$HOST" "echo 'SSH connection OK'" >/dev/null 2>&1; then
    error "SSH connection test failed"
    error "Please ensure ~/.ssh/id_rsa is authorized and server is accessible at $HOST"
    exit 1
fi

# Step 5: Create remote directory if it doesn't exist and ensure permissions
info "Creating remote directory if needed and setting permissions..."
ssh_cmd "$HOST" "mkdir -p $REMOTE_DIR && chmod 755 $REMOTE_DIR && test -w $REMOTE_DIR" || {
    error "Failed to create remote directory or set permissions"
    exit 1
}

# Step 6: Synchronize files to server
info "Synchronizing docker-compose.yml and .env..."
scp_cmd docker-compose.yml .env "$HOST:$REMOTE_DIR/" || {
    error "Failed to copy docker-compose.yml or .env"
    exit 1
}

info "Synchronizing docker/ folder..."
scp_cmd -r docker "$HOST:$REMOTE_DIR/" || {
    error "Failed to copy docker/ folder"
    exit 1
}

info "Synchronizing frontend/ folder (required for build)..."
# Use rsync to exclude node_modules, .next, and other build artifacts
if command -v rsync >/dev/null 2>&1; then
    rsync_cmd --delete \
        --exclude 'node_modules' \
        --exclude '.next' \
        --exclude '.git' \
        --exclude 'dist' \
        --exclude 'build' \
        --exclude '*.log' \
        frontend/ "$HOST:$REMOTE_DIR/frontend/" || {
        error "Failed to sync frontend/ folder"
        exit 1
    }
else
    # Fallback to scp if rsync not available (but will be slower and may have permission issues)
    warn "rsync not found, using scp (may be slower and skip some files)..."
    scp_cmd -r frontend "$HOST:$REMOTE_DIR/" || {
        error "Failed to copy frontend/ folder"
        exit 1
    }
fi

info "Synchronizing backend/ folder (required for build)..."
# Use rsync to exclude __pycache__, .pyc files, and other build artifacts
if command -v rsync >/dev/null 2>&1; then
    rsync_cmd --delete \
        --exclude '__pycache__' \
        --exclude '*.pyc' \
        --exclude '*.pyo' \
        --exclude '.pytest_cache' \
        --exclude '.git' \
        --exclude '*.log' \
        --exclude 'venv' \
        --exclude 'env' \
        backend/ "$HOST:$REMOTE_DIR/backend/" || {
        error "Failed to sync backend/ folder"
        exit 1
    }
else
    # Fallback to scp if rsync not available
    warn "rsync not found, using scp (may be slower and skip some files)..."
    scp_cmd -r backend "$HOST:$REMOTE_DIR/" || {
        error "Failed to copy backend/ folder"
        exit 1
    }
fi

info "Files synchronized successfully ✓"

# Post-sync: Fix permissions for Docker compatibility
info "Fixing permissions for Docker compatibility..."
ssh_cmd "$HOST" << 'PERM_FIX'
  cd /home/ubuntu/automated-trading-platform || exit 1
  # Ensure directories are traversable (755)
  find . -type d ! -perm 755 -exec chmod 755 {} \; 2>/dev/null || true
  # Ensure files are readable (preserve executable bits for scripts)
  find . -type f ! -perm -u+r -exec chmod u+r {} \; 2>/dev/null || true
  # Ensure backend and frontend directories have correct permissions
  [ -d backend ] && find backend -type d -exec chmod 755 {} \; 2>/dev/null || true
  [ -d backend ] && find backend -type f -exec chmod 644 {} \; 2>/dev/null || true
  [ -d frontend ] && find frontend -type d -exec chmod 755 {} \; 2>/dev/null || true
  [ -d frontend ] && find frontend -type f -exec chmod 644 {} \; 2>/dev/null || true
  # Ensure shell scripts are executable
  find . -type f \( -name '*.sh' -o -name '*.bash' \) -exec chmod +x {} \; 2>/dev/null || true
  echo "✅ Permissions fixed for Docker compatibility"
PERM_FIX

# Step 7: Deploy services on remote server
info "Deploying services on remote server..."
ssh_cmd "$HOST" << 'ENDSSH'
    set -euo pipefail
    cd /home/ubuntu/automated-trading-platform
    
    export COMPOSE_PROFILES=aws
    
    echo "Stopping existing services..."
    docker compose --profile aws down || true
    
    echo "Pulling latest images..."
    docker compose --profile aws pull || true
    
    echo "Starting services..."
    docker compose --profile aws up -d
    
    echo "Waiting for services to start..."
    sleep 5
    
    echo "Service status:"
    docker compose --profile aws ps
ENDSSH

if [ $? -eq 0 ]; then
    info "Deployment completed successfully! ✓"
else
    error "Deployment failed. Check the output above for details."
    exit 1
fi

