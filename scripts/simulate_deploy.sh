#!/usr/bin/env bash
set -euo pipefail

# Deployment simulator: runs a full dry-run end-to-end without touching remote

. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

SERVER="${SERVER:-175.41.189.249}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

echo "[SIM] Environment summary"
echo "  SERVER=${SERVER}"
echo "  REMOTE_PROJECT_DIR=${REMOTE_PROJECT_DIR}"
echo "  SSH_KEY=${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo

echo "[SIM] Running pre-deployment check (local only)..."
DRY_RUN=1 ./scripts/pre_deploy_check.sh || {
  echo "[ERROR] Pre-deployment check failed (dry-run). Aborting."
  exit 1
}

echo "[SIM] Simulating start-stack-and-health.sh..."
DRY_RUN=1 SERVER="${SERVER}" REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR}" ./scripts/start-stack-and-health.sh || {
  echo "[ERROR] start-stack-and-health.sh (dry-run) failed. Aborting."
  exit 1
}

echo "[SIM] Simulating start-aws-stack.sh..."
DRY_RUN=1 ./scripts/start-aws-stack.sh "${SERVER}" "${REMOTE_PROJECT_DIR}" || {
  echo "[ERROR] start-aws-stack.sh (dry-run) failed. Aborting."
  exit 1
}

echo "[SUCCESS] Deployment simulation completed. Real deployment safe."


