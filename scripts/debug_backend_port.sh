#!/usr/bin/env bash
set -euo pipefail

# Debug backend port binding and endpoint reachability on the remote host.
# Usage:
#   scripts/debug_backend_port.sh [SERVER] [REMOTE_PROJECT_DIR]
# Defaults:
#   SERVER=175.41.189.249
#   REMOTE_PROJECT_DIR=/home/ubuntu/automated-trading-platform
#
# Requires: scripts/ssh_key.sh (ssh_cmd helper)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=/dev/null
source "$ROOT_DIR/scripts/ssh_key.sh"

SERVER="${1:-175.41.189.249}"
REMOTE_PROJECT_DIR="${2:-/home/ubuntu/automated-trading-platform}"

echo "== Debugging backend port on ${SERVER} =="
echo "Remote project dir: ${REMOTE_PROJECT_DIR}"
echo ""

echo "== docker compose ps (backend-aws) =="
ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws ps backend-aws || docker compose ps backend-aws || true"
echo ""

echo "== Last 80 lines of backend-aws logs =="
ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose logs --no-color --tail=80 backend-aws || true"
echo ""

echo "== Host-level curls to docker-proxy on 127.0.0.1:8002 =="
ssh_cmd "ubuntu@${SERVER}" "curl -s -o /dev/null -w 'health:%{http_code}\n' http://127.0.0.1:8002/api/health || echo 'health FAIL'"
ssh_cmd "ubuntu@${SERVER}" "curl -s -o /dev/null -w 'state:%{http_code}\n'  http://127.0.0.1:8002/api/dashboard/state || echo 'state FAIL'"
echo ""

echo '== Inside container: listener + curls =='
ssh_cmd "ubuntu@${SERVER}" "cd ${REMOTE_PROJECT_DIR} && docker compose --profile aws exec -T backend-aws sh -lc '
  echo \"-- Socket listeners --\";
  (ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null || echo no-ss) | grep :8002 || true;
  echo \"-- Curl internal endpoints --\";
  (curl -s -o /dev/null -w \"health:%{http_code}\n\" http://127.0.0.1:8002/api/health || echo \"health FAIL\");
  (curl -s -o /dev/null -w \"state:%{http_code}\n\"  http://127.0.0.1:8002/api/dashboard/state || echo \"state FAIL\");
'"
echo ""

echo "== Nginx upstream quick check (if present) =="
ssh_cmd "ubuntu@${SERVER}" "grep -nE 'location = /api/dashboard/state|location /api/' /etc/nginx/sites-enabled/dashboard.conf 2>/dev/null || true"
echo ""

echo "== Done =="


