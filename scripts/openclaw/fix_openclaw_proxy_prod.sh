#!/usr/bin/env bash
set -euo pipefail

NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"
OLD="proxy_pass http://52.77.216.100:8080/;"
NEW="proxy_pass http://172.31.3.214:8080/;"

if [[ ! -f "$NGINX_SITE" ]]; then
  echo "ERROR: nginx site file not found: $NGINX_SITE"
  exit 1
fi

TS="$(date +%s)"
# Backup outside sites-enabled so nginx does not load it (avoids "duplicate default server")
BAK_DIR="/etc/nginx/backups"
BAK="${BAK_DIR}/$(basename "$NGINX_SITE").bak.${TS}"

echo "Target: $NGINX_SITE"
echo "Backup: $BAK"

sudo mkdir -p "$BAK_DIR"
sudo cp -a "$NGINX_SITE" "$BAK"

# Count occurrences before
BEFORE="$(sudo grep -cF "$OLD" "$NGINX_SITE" || true)"
echo "Occurrences of OLD before: $BEFORE"

if [[ "$BEFORE" -eq 0 ]]; then
  echo "Nothing to change (already pointing to LAB private IP or OLD not present)."
else
  # Replace ALL occurrences (idempotent). Try macOS sed first, then Linux.
  OLD_ESC="$(printf '%s' "$OLD" | sed 's/[\/&]/\\&/g')"
  if ! sudo sed -i '' "s|$OLD_ESC|$NEW|g" "$NGINX_SITE" 2>/dev/null; then
    sudo sed -i "s|$OLD_ESC|$NEW|g" "$NGINX_SITE"
  fi

  AFTER="$(sudo grep -cF "$OLD" "$NGINX_SITE" || true)"
  echo "Occurrences of OLD after: $AFTER"
fi

echo "Running nginx -t..."
if ! sudo nginx -t; then
  echo "nginx -t FAILED. Restoring backup."
  sudo cp -a "$BAK" "$NGINX_SITE"
  sudo nginx -t || true
  echo "Rollback complete: sudo cp -a '$BAK' '$NGINX_SITE' && sudo systemctl reload nginx"
  exit 1
fi

echo "Reloading nginx..."
sudo systemctl reload nginx

echo
echo "Verify from PROD to LAB (expect 200):"
curl -sS -m 5 -I http://172.31.3.214:8080/ | head -n 20 || true

echo
echo "Verify public path (expect 401 Basic Auth):"
curl -sS -m 8 -I https://dashboard.hilovivo.com/openclaw/ | head -n 20 || true

echo
echo "Rollback command:"
echo "sudo cp -a '$BAK' '$NGINX_SITE' && sudo nginx -t && sudo systemctl reload nginx"
