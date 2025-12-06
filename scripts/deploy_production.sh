#!/usr/bin/env bash
set -euo pipefail

# Production deployment wrapper with explicit confirmation
#
# Usage:
#   SERVER=175.41.189.249 ./scripts/deploy_production.sh
#
# Steps:
#   1) Run pre-deploy checks (local + DRY_RUN)
#   2) Ask for explicit confirmation
#   3) Run real deployment: start-stack-and-health.sh

ROOT_DIR="$(cd "$(dirname "$0")/.."; pwd)"
cd "$ROOT_DIR"

. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

SERVER="${SERVER:-175.41.189.249}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

echo "[INFO] Pre-flight validation..."
./scripts/pre_deploy_check.sh

echo
echo "Are you sure you want to deploy to SERVER=${SERVER}? (y/N): "
read -r REPLY
if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
  echo "[ABORTED] Deployment cancelled."
  exit 1
fi

echo "[DEPLOY] Starting production deployment..."
SERVER="${SERVER}" REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR}" ./scripts/start-stack-and-health.sh

echo
echo "[POST-DEPLOY] Verify from local:"
echo '  curl -k https://dashboard.hilovivo.com/api/health'
echo '  curl -k https://dashboard.hilovivo.com/api/trading/live-status'
echo '  curl -k -X POST https://dashboard.hilovivo.com/api/trading/live-toggle \'
echo '    -H "Content-Type: application/json" \'
echo "    -d '{\"enabled\": true}'"
echo
echo "[DONE] Production deployment completed."


