#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

# Run Crypto.com Exchange auth diagnostic inside the backend container on AWS.
# Prints egress IP and AUTH_OK. No secrets. Execute from repo root.
#
# Usage:
#   cd /Users/carloscruz/automated-trading-platform
#   bash scripts/aws/run_diagnose_exchange_auth_aws.sh
#
# Overrides: REMOTE_HOST, SSH_USER, REMOTE_REPO, CONTAINER_NAME

REMOTE_HOST="${REMOTE_HOST:-hilovivo-aws}"
SSH_USER="${SSH_USER:-ubuntu}"
REMOTE_REPO="${REMOTE_REPO:-/home/ubuntu/automated-trading-platform}"
CONTAINER_NAME="${CONTAINER_NAME:-backend-aws}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
DIAG_SCRIPT="$ROOT_DIR/backend/scripts/diagnose_exchange_auth.py"

if [[ ! -f "$DIAG_SCRIPT" ]]; then
  echo "ERROR: $DIAG_SCRIPT not found" >&2
  exit 2
fi

REMOTE_TMP="/tmp/diagnose_exchange_auth_$$.py"
REMOTE_REPO_SCRIPT="${REMOTE_REPO}/backend/scripts/diagnose_exchange_auth.py"

echo "== SCP script to host /tmp =="
scp "$DIAG_SCRIPT" "${SSH_USER}@${REMOTE_HOST}:${REMOTE_TMP}"

echo "== Copy into repo, detect container, copy script into container, run =="
ssh "${SSH_USER}@${REMOTE_HOST}" "set -e; \
  cp \"${REMOTE_TMP}\" \"${REMOTE_REPO_SCRIPT}\"; \
  rm -f \"${REMOTE_TMP}\"; \
  cd \"${REMOTE_REPO}\"; \
  CONTAINER=\"\"; \
  if docker ps --format '{{.Names}}' | grep -q \"^${CONTAINER_NAME}\$\"; then \
    CONTAINER=\"${CONTAINER_NAME}\"; \
  fi; \
  if [[ -z \"\$CONTAINER\" ]]; then \
    CONTAINER=\"\$(docker ps --format '{{.Names}}' | grep -E 'backend' | head -1)\"; \
  fi; \
  if [[ -z \"\$CONTAINER\" ]]; then \
    echo \"ERROR: no backend container found\" >&2; exit 2; \
  fi; \
  docker cp \"${REMOTE_REPO_SCRIPT}\" \"\$CONTAINER:/app/scripts/diagnose_exchange_auth.py\"; \
  docker exec \"\$CONTAINER\" python3 /app/scripts/diagnose_exchange_auth.py"

echo ""
echo "== Summary (from output above) =="
echo "  Public egress IP = value shown as 'Public egress IP:'"
echo "  AUTH_OK = value shown as 'AUTH_OK:'"
