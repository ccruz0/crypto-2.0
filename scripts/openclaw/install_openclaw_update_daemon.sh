#!/usr/bin/env bash
# Install the OpenClaw update daemon on LAB.
# Run ON the LAB instance (via SSM or SSH).
#
# Usage:
#   cd /home/ubuntu/automated-trading-platform
#   sudo bash scripts/openclaw/install_openclaw_update_daemon.sh
#
# After install, the "Update now" button in OpenClaw can trigger updates
# when the OpenClaw app is modified to call the daemon (see OPENCLAW_UPDATE_FROM_UI.md).
set -e

# Use current dir if we're in the repo, else default
REPO_ROOT="${REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
if [[ -f "$(pwd)/scripts/openclaw/install_openclaw_update_daemon.sh" ]]; then
  REPO_ROOT="$(pwd)"
fi
cd "$REPO_ROOT"

echo "=== Installing OpenClaw update daemon ==="

# Ensure config exists (gateway token required for auth)
if [[ ! -f /opt/openclaw/home-data/openclaw.json ]]; then
  echo "WARNING: /opt/openclaw/home-data/openclaw.json not found."
  echo "Run OpenClaw at least once so the config is created, or run ensure_openclaw_gateway_token.sh"
fi

# Copy systemd unit
sudo cp scripts/openclaw/openclaw-update-daemon.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable openclaw-update-daemon
sudo systemctl start openclaw-update-daemon

echo ""
echo "=== Status ==="
sudo systemctl status openclaw-update-daemon --no-pager
echo ""
echo "Daemon listens on 0.0.0.0:19999. OpenClaw container uses host.docker.internal:19999."
echo "See docs/openclaw/OPENCLAW_UPDATE_FROM_UI.md for OpenClaw repo changes."
