#!/usr/bin/env bash
# Safe render + backend recreate helper for PROD EC2 (run after SSM changes).
# Renders secrets/runtime.env, fixes ownership/permissions, recreates backend-aws,
# waits for health, then verifies deploy secrets. Never prints secret values.
#
# Usage (on PROD EC2, from repo root):
#   bash scripts/aws/render_and_recreate_backend_safe.sh

set -euo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

if [[ "$ROOT_DIR" != "/home/ubuntu/crypto-2.0" && ! -f "$ROOT_DIR/docker-compose.yml" ]]; then
  echo "ERROR: must run from /home/ubuntu/crypto-2.0 or a repo root containing docker-compose.yml" >&2
  exit 1
fi
[[ -f "$ROOT_DIR/docker-compose.yml" ]] || { echo "ERROR: docker-compose.yml not found in $ROOT_DIR" >&2; exit 1; }

HEALTH_TIMEOUT_S="${HEALTH_TIMEOUT_S:-120}"
PING_URL="http://127.0.0.1:8002/ping_fast"
READY_URL="http://127.0.0.1:8002/api/health/ready"

echo "== 1. Render secrets/runtime.env (SSM + .env.aws) =="
sudo bash scripts/aws/render_runtime_env.sh

echo
echo "== 2. Fix runtime.env ownership and permissions =="
sudo chown 10001:10001 secrets/runtime.env
sudo chmod 600 secrets/runtime.env
echo "  secrets/runtime.env -> owner 10001:10001, mode 600"

echo
echo "== 3. Recreate backend-aws =="
sudo docker compose --profile aws up -d --force-recreate backend-aws

echo
echo "== 4. Wait for health (up to ${HEALTH_TIMEOUT_S}s) =="
deadline=$(( $(date +%s) + HEALTH_TIMEOUT_S ))
healthy=no
while (( $(date +%s) < deadline )); do
  ping_status="$(curl -s -m 5 "$PING_URL" 2>/dev/null || true)"
  ready_status="$(curl -s -m 10 "$READY_URL" 2>/dev/null || true)"
  if echo "$ping_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"' \
     && echo "$ready_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
    healthy=yes
    break
  fi
  sleep 5
done

if [[ "$healthy" != "yes" ]]; then
  echo "ERROR: backend did not become healthy within ${HEALTH_TIMEOUT_S}s" >&2
  echo "  /ping_fast: ${ping_status:-<no response>}" >&2
  echo "  /api/health/ready: ${ready_status:-<no response>}" >&2
  echo "Inspect: sudo docker compose --profile aws logs backend-aws --tail=100" >&2
  exit 1
fi
echo "  /ping_fast: ok"
echo "  /api/health/ready: ready"

echo
echo "== 5. Verify deploy secrets (presence only) =="
VERIFY_OUT="$(./scripts/verify_deploy_secrets.sh 2>&1)" || {
  echo "$VERIFY_OUT" | sed 's/^/  /'
  echo "ERROR: verify_deploy_secrets.sh failed" >&2
  exit 1
}
echo "$VERIFY_OUT" | sed 's/^/  /'

AUTH_MODE="$(echo "$VERIFY_OUT" | sed -n 's/^[[:space:]]*auth_mode:[[:space:]]*//p' | head -1)"
echo
echo "== Final =="
echo "auth_mode: ${AUTH_MODE:-unknown}"
echo "Backend recreated and healthy."
