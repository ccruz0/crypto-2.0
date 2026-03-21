#!/usr/bin/env bash
# Deploy OpenClaw basepath nginx fix to PROD.
# Run on EC2 (PROD) or via: ssh ubuntu@dashboard.hilovivo.com 'bash -s' < scripts/openclaw/deploy_openclaw_baspath_nginx.sh
set -euo pipefail

REPO="${REPO:-/home/ubuntu/automated-trading-platform}"
cd "$REPO" || exit 1

echo "=== Deploying OpenClaw basepath nginx fix ==="
git pull
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard
sudo nginx -t
sudo systemctl reload nginx
echo "=== Done ==="

echo ""
echo "=== Validation ==="
echo "Testing redirect from /openclaw/ (expect Location to contain /openclaw/)..."
curl -sS -I --max-time 5 "https://dashboard.hilovivo.com/openclaw/" 2>/dev/null | grep -i location || echo "(no Location header)"
echo ""
echo "If Location shows /openclaw/containers (not /containers), fix is active."
