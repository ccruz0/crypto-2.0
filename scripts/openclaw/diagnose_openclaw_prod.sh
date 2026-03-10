#!/usr/bin/env bash
# Run on PROD (atp-rebuild-2026) via EC2 Instance Connect or SSH.
# Captures the 5 diagnostics needed to fix OpenClaw at https://dashboard.hilovivo.com/openclaw/
# Usage: bash scripts/openclaw/diagnose_openclaw_prod.sh
# Paste the full output for diagnosis.
set -euo pipefail

echo "=========================================="
echo "a) openclaw location block (from nginx -T)"
echo "=========================================="
sudo nginx -T 2>&1 | sed -n '/location \/openclaw/,/}/p' || true

echo ""
echo "=========================================="
echo "b) curl -I http://localhost/openclaw/"
echo "=========================================="
curl -sI http://localhost/openclaw/ 2>&1 | head -20

echo ""
echo "=========================================="
echo "c) PROD -> LAB 172.31.3.214:8080"
echo "=========================================="
curl -sI -m 3 http://172.31.3.214:8080/ 2>&1 | head -20

echo ""
echo "=========================================="
echo "d) nginx error.log (last 80 lines)"
echo "=========================================="
sudo tail -n 80 /var/log/nginx/error.log 2>&1

echo ""
echo "=========================================="
echo "e) nginx listen sockets (ss -lntp | grep nginx)"
echo "=========================================="
sudo ss -lntp 2>&1 | grep nginx || true

echo ""
echo "=========================================="
echo "LAB_PRIVATE_IP=172.31.3.214 OPENCLAW_PORT=8080"
echo "=========================================="
