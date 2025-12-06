#!/usr/bin/env bash
set -euo pipefail

# Start AWS profile services on remote server and run health checks
# Usage:
#   SERVER=175.41.189.249 ./scripts/start-aws-stack.sh [/remote/project/path]
# Defaults:
#   SERVER (env or $1) required; remote project path defaults to /home/ubuntu/automated-trading-platform

# Load unified SSH helper
. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

SERVER="${SERVER:-${1:-}}"
REMOTE_PROJECT_DIR="${2:-/home/ubuntu/automated-trading-platform}"
if [[ -z "${SERVER}" ]]; then
  echo "❌ SERVER not specified. Set SERVER env or pass as first argument."
  exit 1
fi

banner() {
  echo
  echo "============================================================"
  echo "$@"
  echo "============================================================"
}

step() {
  echo "➡️  $@"
}

ok() {
  echo "✅ $@"
}

warn() {
  echo "⚠️  $@"
}

err() {
  echo "❌ $@"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { err "Missing required command: $1"; exit 1; }
}

require_cmd bash
echo "[SSH] Using key: ${SSH_KEY:-$HOME/.ssh/id_rsa}"
echo "[SSH] Testing connection to ubuntu@${SERVER}..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  if ! ssh_cmd "ubuntu@${SERVER}" 'echo SSH OK'; then
    err "SSH test failed to ubuntu@${SERVER}"
    exit 1
  fi
else
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} 'echo SSH OK'"
fi

banner "Starting AWS stack on ubuntu@${SERVER}"
step "Remote project directory: ${REMOTE_PROJECT_DIR}"

step "Pulling images on remote (aws profile)..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws pull || true"
else
  echo "[DRY_RUN] Resolved:"
  echo "  SERVER=${SERVER}"
  echo "  REMOTE_PROJECT_DIR=${REMOTE_PROJECT_DIR}"
  echo "  SSH_CMD=ssh -i \"${SSH_KEY:-$HOME/.ssh/id_rsa}\" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
  echo "[DRY_RUN] Will run in order:"
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws pull || true\""
fi

step "Bringing up services (db, gluetun, backend-aws, frontend-aws) on remote..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws up -d db gluetun backend-aws frontend-aws"
else
  echo "[DRY_RUN] Services to start: db, gluetun, backend-aws, frontend-aws"
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws up -d db gluetun backend-aws frontend-aws\""
fi
ok "Services started (requested) on remote"

step "Waiting for initial stabilization..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  sleep 8
else
  echo "[DRY_RUN] Skipping sleep/stabilization"
fi

step "Current service status (remote):"
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws ps || true"
else
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws ps || true\""
fi

step "Running health checks (remote)..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  BACKEND_CODE="$(ssh_cmd "ubuntu@${SERVER}" "curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/ping_fast || true")"
  FRONTEND_CODE="$(ssh_cmd "ubuntu@${SERVER}" "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 || true")"
else
  echo "[DRY_RUN] Health checks to run:"
  echo "  - backend: curl http://localhost:8002/ping_fast"
  echo "  - frontend: curl http://localhost:3000"
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/ping_fast || true\""
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 || true\""
  BACKEND_CODE="DRY"
  FRONTEND_CODE="DRY"
fi

echo "Backend HTTP: ${BACKEND_CODE}"
echo "Frontend HTTP: ${FRONTEND_CODE}"

HEALTH_OK=true
if [[ "${BACKEND_CODE}" != "200" ]]; then
  warn "Backend not healthy yet (expected 200)."
  HEALTH_OK=false
fi
if [[ "${FRONTEND_CODE}" != "200" && "${FRONTEND_CODE}" != "302" ]]; then
  warn "Frontend not healthy yet (expected 200/302)."
  HEALTH_OK=false
fi

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  ok "DRY_RUN: Health checks simulated."
  exit 0
fi
if [[ "${HEALTH_OK}" == "true" ]]; then
  ok "Services healthy."
  exit 0
fi

warn "Health checks failed. Showing recent logs (tail 200) from remote..."
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose logs --no-color --tail=200 gluetun backend-aws frontend-aws || true"
else
  echo "[DRY_RUN] ssh_cmd ubuntu@${SERVER} \"cd ${REMOTE_PROJECT_DIR} && docker compose logs --no-color --tail=200 gluetun backend-aws frontend-aws || true\""
fi

err "AWS stack not healthy yet. Investigate logs above."
exit 1

# SSH dry-run executed earlier


