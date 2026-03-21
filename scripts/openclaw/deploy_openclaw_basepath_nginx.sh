#!/usr/bin/env bash
# Deploy dashboard nginx config to the file nginx actually loads (not sites-available/dashboard).
# Run on EC2 (PROD) or: ssh ubuntu@dashboard.hilovivo.com 'cd /home/ubuntu/automated-trading-platform && ./scripts/openclaw/deploy_openclaw_basepath_nginx.sh'
set -euo pipefail

REPO="${REPO:-/home/ubuntu/automated-trading-platform}"
cd "$REPO" || exit 1

# nginx includes sites-enabled/*; default is usually a symlink to sites-available/default
if [ ! -L /etc/nginx/sites-enabled/default ] && [ ! -f /etc/nginx/sites-enabled/default ]; then
  echo "ERROR: /etc/nginx/sites-enabled/default not found. Set NGINX_SITE_TARGET manually."
  exit 1
fi

NGINX_SITE_TARGET="${NGINX_SITE_TARGET:-$(readlink -f /etc/nginx/sites-enabled/default)}"
echo "=== Deploying nginx/dashboard.conf -> $NGINX_SITE_TARGET ==="
git pull
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
