#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Install Health Monitor Service
# ============================================
# This script installs the health monitor as a systemd service on the AWS server
#
# Usage:
#   ./install_health_monitor.sh
# ============================================

HOST="${HOST:-ubuntu@175.41.189.249}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/automated-trading-platform}"
# Load unified SSH helper
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if scripts exist locally
if [ ! -f "scripts/health_monitor.sh" ]; then
    error "scripts/health_monitor.sh not found"
    exit 1
fi

if [ ! -f "scripts/health_monitor.service" ]; then
    error "scripts/health_monitor.service not found"
    exit 1
fi

info "Installing health monitor on server..."

# Copy scripts to server
scp_cmd scripts/health_monitor.sh "$HOST:$REMOTE_DIR/scripts/" || {
    error "Failed to copy health_monitor.sh"
    exit 1
}

# Make script executable
ssh_cmd "$HOST" "chmod +x $REMOTE_DIR/scripts/health_monitor.sh" || {
    error "Failed to make script executable"
    exit 1
}

# Copy systemd service file
scp_cmd scripts/health_monitor.service "$HOST:/tmp/health_monitor.service" || {
    error "Failed to copy service file"
    exit 1
}

# Install and enable service
ssh_cmd "$HOST" << 'ENDSSH'
    set -euo pipefail
    
    # Copy service file to systemd
    sudo cp /tmp/health_monitor.service /etc/systemd/system/health_monitor.service
    
    # Create logs directory
    mkdir -p /home/ubuntu/automated-trading-platform/logs
    
    # Reload systemd
    sudo systemctl daemon-reload
    
    # Enable service (start on boot)
    sudo systemctl enable health_monitor.service
    
    # Start service
    sudo systemctl start health_monitor.service
    
    # Check status
    sleep 2
    sudo systemctl status health_monitor.service --no-pager | head -10
    
    echo "Health monitor service installed and started"
ENDSSH

if [ $? -eq 0 ]; then
    info "Health monitor installed successfully!"
    info ""
    info "To check status:"
    info "  ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'sudo systemctl status health_monitor'"
    info ""
    info "To view logs:"
    info "  ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'tail -f /home/ubuntu/automated-trading-platform/logs/health_monitor.log'"
else
    error "Failed to install health monitor"
    exit 1
fi

