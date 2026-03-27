#!/usr/bin/env bash
# Deploy dashboard nginx config to the file nginx actually loads (not sites-available/dashboard).
# Run on EC2 (PROD) or: ssh ubuntu@dashboard.hilovivo.com 'cd /home/ubuntu/crypto-2.0 && ./scripts/openclaw/deploy_openclaw_basepath_nginx.sh'
#
# Repo root is detected from this script's path unless you set REPO=...
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
_DEFAULT_REPO="$(cd "$_SCRIPT_DIR/../.." && pwd)"
REPO="${REPO:-$_DEFAULT_REPO}"
cd "$REPO" || { echo "ERROR: cannot cd to REPO=$REPO"; exit 1; }
if [ ! -f "$REPO/nginx/dashboard.conf" ]; then
  echo "ERROR: nginx/dashboard.conf not found under: $REPO"
  echo "Fix: cd to your automated-trading-platform clone, or: REPO=/path/to/automated-trading-platform $0"
  exit 1
fi

# nginx includes sites-enabled/*; default is usually a symlink to sites-available/default
if [ ! -L /etc/nginx/sites-enabled/default ] && [ ! -f /etc/nginx/sites-enabled/default ]; then
  echo "ERROR: /etc/nginx/sites-enabled/default not found. Set NGINX_SITE_TARGET manually."
  exit 1
fi

NGINX_SITE_TARGET="${NGINX_SITE_TARGET:-$(readlink -f /etc/nginx/sites-enabled/default)}"
echo "=== Deploying nginx/dashboard.conf -> $NGINX_SITE_TARGET ==="
git pull

# dashboard.conf uses limit_req zone=api_limit and monitoring_limit; they must exist in http {}.
# Without them: nginx: [emerg] zero size shared memory zone "monitoring_limit"
if [ -f "$REPO/nginx/rate_limiting_zones.conf" ]; then
  echo "=== Ensuring rate limit zones (api_limit, monitoring_limit) ==="
  sudo cp "$REPO/nginx/rate_limiting_zones.conf" /etc/nginx/rate_limiting_zones.conf
  if ! grep -qF 'include /etc/nginx/rate_limiting_zones.conf;' /etc/nginx/nginx.conf 2>/dev/null; then
    echo "Adding include /etc/nginx/rate_limiting_zones.conf; to nginx.conf (backup created)..."
    sudo cp -a /etc/nginx/nginx.conf "/etc/nginx/nginx.conf.bak.$(date +%s)"
    sudo sed -i '/^http {/a\    include /etc/nginx/rate_limiting_zones.conf;' /etc/nginx/nginx.conf
  fi
fi

sudo cp nginx/dashboard.conf "$NGINX_SITE_TARGET"
sudo nginx -t
sudo systemctl reload nginx
echo "=== Done ==="

echo ""
echo "=== Validation ==="
echo "Without auth: expect 401 (Basic Auth) — no Location (request never reaches OpenClaw)."
curl -sS -I --max-time 5 "https://dashboard.hilovivo.com/openclaw/" 2>/dev/null | head -5
echo ""
if [ -n "${OPENCLAW_BASIC_AUTH:-}" ]; then
  echo "With OPENCLAW_BASIC_AUTH=user:pass — Location must stay under /openclaw/:"
  curl -sS -I --max-time 10 -u "$OPENCLAW_BASIC_AUTH" "https://dashboard.hilovivo.com/openclaw/" 2>/dev/null | grep -iE '^location:' || echo "(no Location — may be 200)"
else
  echo "To test redirect rewrite, run (replace USER:PASS):"
  echo '  curl -sS -I -u USER:PASS https://dashboard.hilovivo.com/openclaw/ | grep -i location'
  echo "Or: OPENCLAW_BASIC_AUTH=user:pass $0  (re-run this script with env set)"
fi
