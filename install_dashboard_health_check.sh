#!/bin/bash
# Install Dashboard Health Check Service
# This script installs the dashboard health check as a systemd timer

set -euo pipefail

HOST="${HOST:-ubuntu@175.41.189.249}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/automated-trading-platform}"
# Load unified SSH helper
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "[INFO] Installing dashboard health check service..."

# Check if SSH key exists
echo "[INFO] Using SSH key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"

# Copy scripts to server
echo "[INFO] Copying scripts to server..."
scp_cmd \
    scripts/dashboard_health_check.sh \
    scripts/dashboard_health_check.service \
    scripts/dashboard_health_check.timer \
    "$HOST:$REMOTE_DIR/scripts/"

# Create logs directory
echo "[INFO] Creating logs directory..."
ssh_cmd "$HOST" "mkdir -p $REMOTE_DIR/logs"

# Load environment variables from .env file
echo "[INFO] Loading environment variables from .env..."
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "$HOST" "grep '^TELEGRAM_BOT_TOKEN=' $REMOTE_DIR/.env | cut -d '=' -f2- | tr -d '\"' | tr -d \"'\"" || echo "")
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "$HOST" "grep '^TELEGRAM_CHAT_ID=' $REMOTE_DIR/.env | cut -d '=' -f2- | tr -d '\"' | tr -d \"'\"" || echo "")

# Update service file with environment variables
echo "[INFO] Updating service file with environment variables..."
ssh -i "$KEY_PATH" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "$HOST" "sed -i 's|\${TELEGRAM_BOT_TOKEN}|$TELEGRAM_BOT_TOKEN|g' $REMOTE_DIR/scripts/dashboard_health_check.service && \
             sed -i 's|\${TELEGRAM_CHAT_ID}|$TELEGRAM_CHAT_ID|g' $REMOTE_DIR/scripts/dashboard_health_check.service"

# Install systemd service and timer
echo "[INFO] Installing systemd service and timer..."
ssh -i "$KEY_PATH" \
    -o StrictHostKeyChecking=no \
    -o UserKnownHostsFile=/dev/null \
    "$HOST" "sudo cp $REMOTE_DIR/scripts/dashboard_health_check.service /etc/systemd/system/ && \
             sudo cp $REMOTE_DIR/scripts/dashboard_health_check.timer /etc/systemd/system/ && \
             sudo systemctl daemon-reload && \
             sudo systemctl enable dashboard_health_check.timer && \
             sudo systemctl start dashboard_health_check.timer && \
             sudo systemctl status dashboard_health_check.timer --no-pager"

echo "[INFO] Dashboard health check service installed successfully!"
echo "[INFO] Service will run every 20 minutes"
echo "[INFO] Check status with: sudo systemctl status dashboard_health_check.timer"
echo "[INFO] View logs with: sudo journalctl -u dashboard_health_check.service -f"

