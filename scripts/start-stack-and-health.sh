#!/usr/bin/env bash
set -euo pipefail

# One-touch: start AWS stack, install health monitors, and print verification commands
#
# Usage:
#   SERVER=175.41.189.249 ./scripts/start-stack-and-health.sh
#   ./scripts/start-stack-and-health.sh 175.41.189.249
#
# Defaults:
#   SERVER defaults to 175.41.189.249 if not provided

# Load unified SSH helper
. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

SERVER="${SERVER:-${1:-175.41.189.249}}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

echo "[INFO] Using SERVER=${SERVER}"
echo "[SSH] Using key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"

# 1) Start AWS stack remotely (honor DRY_RUN)
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[DRY_RUN] ./scripts/start-aws-stack.sh \"${SERVER}\" \"${REMOTE_PROJECT_DIR}\""
else
  ./scripts/start-aws-stack.sh "${SERVER}" "${REMOTE_PROJECT_DIR}"
fi

# 2) Install/enable health monitor (systemd timer on remote host)
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[DRY_RUN] HOST=ubuntu@${SERVER} ./install_health_monitor.sh"
else
  HOST="ubuntu@${SERVER}" ./install_health_monitor.sh
fi

# 3) Install dashboard health check timer (remote host)
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "[DRY_RUN] HOST=ubuntu@${SERVER} ./install_dashboard_health_check.sh"
else
  HOST="ubuntu@${SERVER}" ./install_dashboard_health_check.sh
fi

echo
echo "[INFO] To verify from your local machine:"
echo '  curl -k https://dashboard.hilovivo.com/api/health'
echo '  curl -k https://dashboard.hilovivo.com/api/trading/live-status'
echo '  curl -k -X POST https://dashboard.hilovivo.com/api/trading/live-toggle \'
echo '    -H "Content-Type: application/json" \'
echo "    -d '{\"enabled\": true}'"
echo
echo "[DONE] Stack started and monitors installed."


