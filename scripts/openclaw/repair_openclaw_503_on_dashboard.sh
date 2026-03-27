#!/usr/bin/env bash
# Run ON the dashboard EC2 (nginx for dashboard.hilovivo.com). No Mac path, no SSM.
#
# Usage (from repo on the server):
#   cd /home/ubuntu/crypto-2.0
#   git pull origin main
#   bash scripts/openclaw/repair_openclaw_503_on_dashboard.sh
#
# Does: git pull → deploy_openclaw_basepath_nginx.sh → force_openclaw_proxy_8080_on_prod → reload nginx → curl checks.
# OpenClaw containers must still run on the LAB; open LAB SG TCP 8080 from this host if curl to LAB fails.
#
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$_SCRIPT_DIR/../.." && pwd)"
cd "$REPO"

LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"

if [[ ! -d /etc/nginx/sites-enabled ]]; then
  echo "ERROR: /etc/nginx/sites-enabled missing — not the nginx dashboard host."
  exit 2
fi

echo "=== Repo: $REPO ==="
git pull origin main 2>/dev/null || git pull 2>/dev/null || true

echo "=== Deploy nginx from repo ==="
bash scripts/openclaw/deploy_openclaw_basepath_nginx.sh

echo "=== Normalize openclaw proxy_pass (LAB:$LAB_PRIVATE_IP port $OPENCLAW_PORT) ==="
export LAB_PRIVATE_IP OPENCLAW_PORT
sudo -E bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh || true

sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "=== Public /openclaw/ (expect 401 without auth) ==="
curl -sS -m 12 -I "https://dashboard.hilovivo.com/openclaw/" | head -15 || true

echo ""
echo "=== From this host to LAB upstream (must work for no 503 after login) ==="
curl -sS -m 6 -I "http://${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/" | head -10 || true

echo ""
echo "Done. If LAB curl failed: start OpenClaw on LAB (docker compose openclaw) and open LAB security group TCP $OPENCLAW_PORT from $(curl -sS --max-time 2 http://169.254.169.254/latest/meta-data/local-ipv4 2>/dev/null || echo THIS_HOST_PRIVATE_IP)."
