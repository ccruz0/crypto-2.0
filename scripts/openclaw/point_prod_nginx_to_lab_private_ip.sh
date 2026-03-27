#!/usr/bin/env bash
# Run this ON PROD (atp-rebuild-2026) to point /openclaw/ to LAB private IP.
# LAB = atp-lab-ssm-clean (172.31.3.214). No args; uses canonical IP.
#
# Usage on PROD (SSH or Instance Connect):
#   cd /home/ubuntu/crypto-2.0
#   sudo bash scripts/openclaw/point_prod_nginx_to_lab_private_ip.sh

set -e
LAB_PRIVATE_IP="${1:-172.31.3.214}"

echo "=== OpenClaw upstream: set to LAB private IP $LAB_PRIVATE_IP:8080 ==="
CONFIGS=$(grep -l "location.*openclaw" /etc/nginx/sites-enabled/* 2>/dev/null || true)
if [[ -z "$CONFIGS" ]]; then
  echo "No nginx config with openclaw block found in /etc/nginx/sites-enabled/"
  sudo nginx -T 2>/dev/null | sed -n '/openclaw/,+5p' || true
  exit 1
fi
TS=$(date +%s)
for CONFIG in $CONFIGS; do
  echo "Config: $CONFIG"
  sudo cp -a "$CONFIG" "${CONFIG}.bak.${TS}"
  sudo sed -i "s|proxy_pass http://[^:]*:8080/;|proxy_pass http://${LAB_PRIVATE_IP}:8080/;|" "$CONFIG"
  sudo sed -i "s|proxy_pass http://[^:]*:8081/;|proxy_pass http://${LAB_PRIVATE_IP}:8080/;|" "$CONFIG"
  sudo grep -n "proxy_pass.*808" "$CONFIG" || true
done
sudo nginx -t
sudo systemctl reload nginx
echo "=== Verify ==="
curl -sI "https://dashboard.hilovivo.com/openclaw/" | head -n 20
