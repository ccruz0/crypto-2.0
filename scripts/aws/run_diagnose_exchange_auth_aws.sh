#!/usr/bin/env bash
set -euo pipefail
set +x 2>/dev/null || true

# Run Crypto.com Exchange auth diagnostic inside backend container on AWS.
# Execute from repo root. No secrets printed.
#
# Usage:
#   cd /Users/carloscruz/automated-trading-platform
#   bash scripts/aws/run_diagnose_exchange_auth_aws.sh

REMOTE_HOST="${REMOTE_HOST:-hilovivo-aws}"
SSH_USER="${SSH_USER:-ubuntu}"
REMOTE_REPO="${REMOTE_REPO:-/home/ubuntu/automated-trading-platform}"
CONTAINER_NAME="${CONTAINER_NAME:-backend-aws}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"
DIAG_SCRIPT="$ROOT_DIR/backend/scripts/diagnose_exchange_auth.py"
REMOTE_TMP="/tmp/diagnose_exchange_auth.py"

if [[ ! -f "$DIAG_SCRIPT" ]]; then
  echo "ERROR: $DIAG_SCRIPT not found" >&2
  exit 2
fi

echo "== SCP script to host /tmp =="
scp "$DIAG_SCRIPT" "${SSH_USER}@${REMOTE_HOST}:${REMOTE_TMP}"

OUTPUT=$(ssh "${SSH_USER}@${REMOTE_HOST}" "set -euo pipefail
  CONTAINER=\"\"
  if docker ps --format '{{.Names}}' | grep -q \"^${CONTAINER_NAME}\$\"; then
    CONTAINER=\"${CONTAINER_NAME}\"
  fi
  if [[ -z \"\$CONTAINER\" ]]; then
    CONTAINER=\$(docker ps --format '{{.Names}}' | grep -E 'backend' | head -1 || true)
  fi
  if [[ -z \"\$CONTAINER\" ]]; then
    echo \"ERROR: no backend container found\" >&2
    docker ps >&2
    exit 2
  fi
  docker cp \"${REMOTE_TMP}\" \"\$CONTAINER:/tmp/diagnose_exchange_auth.py\"
  docker exec \"\$CONTAINER\" sh -c 'mkdir -p /app/scripts && cp /tmp/diagnose_exchange_auth.py /app/scripts/'
  echo \"CONTAINER_USED:\$CONTAINER\"
  docker exec \"\$CONTAINER\" python3 /app/scripts/diagnose_exchange_auth.py
")

CONTAINER_USED=$(echo "$OUTPUT" | grep -E "^CONTAINER_USED:" | sed -E 's/^CONTAINER_USED://')
IP_LINE=$(echo "$OUTPUT" | grep -E "^Public egress IP:" | sed -E 's/^Public egress IP: *//')
AUTH_LINE=$(echo "$OUTPUT" | grep -E "^AUTH_OK:" | sed -E 's/^AUTH_OK: *//')

echo "$OUTPUT" | grep -v "^CONTAINER_USED:"

echo ""
echo "== Summary =="
echo "  contenedor usado: ${CONTAINER_USED:-<unknown>}"
echo "  IP detectada: ${IP_LINE:-<unknown>}"
echo "  AUTH_OK: ${AUTH_LINE:-<unknown>}"
