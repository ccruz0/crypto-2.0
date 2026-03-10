#!/usr/bin/env bash
# Run ON PROD only (EC2 Instance Connect or SSH to dashboard host).
# Forces every nginx site file that contains "openclaw" to proxy_pass LAB:8080.
# Use when fix_504_via_eice still leaves https://dashboard.hilovivo.com/openclaw/ at 502
# but curl from PROD to http://172.31.3.214:8080/ returns 200.
#
# Usage on PROD (raw — repo origin is crypto-2.0):
#   curl -sSL https://raw.githubusercontent.com/ccruz0/crypto-2.0/main/scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh | sudo bash
# Or after git pull in repo dir on PROD:
#   cd /home/ubuntu/automated-trading-platform && sudo bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh
#
# Env (optional):
#   LAB_PRIVATE_IP=172.31.3.214 OPENCLAW_PORT=8080

set -euo pipefail

LAB="${LAB_PRIVATE_IP:-172.31.3.214}"
PORT="${OPENCLAW_PORT:-8080}"
NEW="proxy_pass http://${LAB}:${PORT}/;"

if [[ ! -d /etc/nginx/sites-enabled ]]; then
  echo "ERROR: Not on nginx host (no /etc/nginx/sites-enabled). Run on PROD."
  exit 2
fi

echo "=== Forcing openclaw proxy_pass -> ${LAB}:${PORT} in all sites-enabled files that mention openclaw ==="
TS=$(date +%s)
for f in /etc/nginx/sites-enabled/*; do
  [[ -f "$f" ]] || continue
  if ! grep -q openclaw "$f" 2>/dev/null; then
    continue
  fi
  echo "--- $f ---"
  sudo cp -a "$f" "${f}.bak.force-openclaw.${TS}"
  # Normalize common broken upstreams to NEW (idempotent if already NEW)
  sudo sed -i \
    -e "s|proxy_pass http://52.77.216.100:8080/;|$NEW|g" \
    -e "s|proxy_pass http://52.77.216.100:8081/;|$NEW|g" \
    -e "s|proxy_pass http://${LAB}:8081/;|$NEW|g" \
    -e "s|proxy_pass http://${LAB}:8080/;|$NEW|g" \
    "$f"
  grep -n "proxy_pass" "$f" | grep -E 'openclaw|8080|8081' || grep -n "proxy_pass" "$f" | head -20
done

echo ""
echo "=== nginx -t && reload ==="
sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "=== curl public (expect 401, not 502) ==="
curl -sS -m 10 -I "https://dashboard.hilovivo.com/openclaw/" | head -15 || true

echo ""
echo "Rollback per file: sudo cp -a <file>.bak.force-openclaw.${TS} <file> && sudo nginx -t && sudo systemctl reload nginx"
