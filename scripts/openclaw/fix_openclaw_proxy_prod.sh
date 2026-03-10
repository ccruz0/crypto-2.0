#!/usr/bin/env bash
# Fix /openclaw/ proxy on PROD: point to LAB private IP. Backups go to /etc/nginx/backups/
# only; never create backups in sites-enabled (avoids "duplicate default server").
# Run ON PROD (atp-rebuild-2026). Idempotent.
# Do NOT run on your Mac — nginx configs live only on the EC2 Dashboard host.
set -euo pipefail

if [[ ! -d /etc/nginx/sites-enabled ]] && [[ -z "${FORCE_LOCAL_NGINX_FIX:-}" ]]; then
  echo "ERROR: /etc/nginx/sites-enabled not found."
  echo "This script must run ON the Dashboard EC2 instance (Ubuntu), not on your Mac."
  echo "  1) AWS Console → EC2 → atp-rebuild-2026 → Connect → EC2 Instance Connect"
  echo "  2) cd /home/ubuntu/automated-trading-platform && git pull"
  echo "  3) sudo OPENCLAW_PORT=8080 LAB_PRIVATE_IP=172.31.3.214 bash scripts/openclaw/fix_openclaw_proxy_prod.sh"
  echo "Or from your Mac: ./scripts/openclaw/fix_504_via_eice.sh   (SSHs to PROD for you)"
  exit 2
fi

NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/default}"
BAK_DIR="/etc/nginx/backups"
LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
# Must match LAB host publish port. docker-compose.openclaw.yml uses 8080:18789 — default 8080.
# If LAB uses -p 8081:18789 instead, run with OPENCLAW_PORT=8081.
OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"
OLD="proxy_pass http://52.77.216.100:8080/;"
NEW="proxy_pass http://${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/;"
OLD_PUBLIC_8081="proxy_pass http://52.77.216.100:8081/;"

log() { echo "[$(date +%Y-%m-%dT%H:%M:%S)] $*"; }

# Apply the same proxy_pass replacements to a single nginx config file (Ubuntu sed -i).
replace_openclaw_upstream_in_file() {
  local SITE_FILE="$1"
  [[ -f "$SITE_FILE" ]] || return 0
  sudo grep -qE 'location\s+(\^~\s+)?/openclaw' "$SITE_FILE" 2>/dev/null || return 0
  local changed=0
  if sudo grep -qF "$OLD" "$SITE_FILE" 2>/dev/null; then
    local OLD_ESC
    OLD_ESC="$(printf '%s' "$OLD" | sed 's/[\/&]/\\&/g')"
    sudo sed -i "s|$OLD_ESC|$NEW|g" "$SITE_FILE" 2>/dev/null || sudo sed -i "s|$OLD_ESC|$NEW|g" "$SITE_FILE"
    changed=1
  fi
  if sudo grep -qF "$OLD_PUBLIC_8081" "$SITE_FILE" 2>/dev/null; then
    local ESC
    ESC="$(printf '%s' "$OLD_PUBLIC_8081" | sed 's/[\/&]/\\&/g')"
    sudo sed -i "s|$ESC|$NEW|g" "$SITE_FILE" 2>/dev/null || true
    changed=1
  fi
  local OLD2="proxy_pass http://${LAB_PRIVATE_IP}:8080/;"
  local OLD3="proxy_pass http://${LAB_PRIVATE_IP}:8081/;"
  if [[ "${OPENCLAW_PORT}" != "8080" ]] && sudo grep -qF "$OLD2" "$SITE_FILE" 2>/dev/null; then
    local OLD2_ESC
    OLD2_ESC="$(printf '%s' "$OLD2" | sed 's/[\/&]/\\&/g')"
    sudo sed -i "s|$OLD2_ESC|$NEW|g" "$SITE_FILE" 2>/dev/null || true
    changed=1
  fi
  if [[ "${OPENCLAW_PORT}" != "8081" ]] && sudo grep -qF "$OLD3" "$SITE_FILE" 2>/dev/null; then
    local OLD3_ESC
    OLD3_ESC="$(printf '%s' "$OLD3" | sed 's/[\/&]/\\&/g')"
    sudo sed -i "s|$OLD3_ESC|$NEW|g" "$SITE_FILE" 2>/dev/null || true
    changed=1
  fi
  # If OPENCLAW_PORT is 8080 but file still has LAB:8081, force to NEW
  if [[ "${OPENCLAW_PORT}" == "8080" ]] && sudo grep -qF "$OLD3" "$SITE_FILE" 2>/dev/null; then
    local OLD3_ESC
    OLD3_ESC="$(printf '%s' "$OLD3" | sed 's/[\/&]/\\&/g')"
    sudo sed -i "s|$OLD3_ESC|$NEW|g" "$SITE_FILE" 2>/dev/null || true
    changed=1
  fi
  if [[ "$changed" -eq 1 ]]; then
    log "Updated openclaw proxy_pass in $SITE_FILE -> ${LAB_PRIVATE_IP}:${OPENCLAW_PORT}"
  fi
}

if [[ ! -f "$NGINX_SITE" ]]; then
  log "ERROR: nginx site file not found: $NGINX_SITE"
  # PROD may use only dashboard.conf — try to find any file with openclaw and use it
  CAND=$(grep -l "openclaw" /etc/nginx/sites-enabled/* 2>/dev/null | head -1 || true)
  if [[ -n "$CAND" ]]; then
    log "Hint: default missing; openclaw appears in: $CAND — re-run with NGINX_SITE=$CAND"
  else
    log "Run on PROD (SSH/Instance Connect). On Mac use: ./scripts/openclaw/fix_504_via_eice.sh"
  fi
  exit 1
fi

# --- Safety guard: only edit PROD HTTPS server (listen 443 + dashboard.hilovivo.com) ---
if ! sudo grep -qE 'listen\s+.*(\[::\]:)?443(\s|;)' "$NGINX_SITE"; then
  printf '\033[31mFATAL: Target file does not contain listen 443 (not the intended HTTPS server block). Refusing to edit.\033[0m\n'
  exit 2
fi
if [[ "${ALLOW_ANY_SERVERNAME:-0}" != "1" ]]; then
  if ! sudo grep -q 'server_name dashboard.hilovivo.com' "$NGINX_SITE"; then
    printf '\033[31mFATAL: Target file does not contain server_name dashboard.hilovivo.com. Refusing to edit. Set ALLOW_ANY_SERVERNAME=1 to bypass.\033[0m\n'
    exit 2
  fi
fi

# --- Step 1: Ensure /etc/nginx/backups exists ---
log "Step 1: Ensure $BAK_DIR exists"
sudo mkdir -p "$BAK_DIR"
log "Step 1: OK"

# --- Step 2: Move any *.bak* or *.backup* from sites-enabled to backups ---
log "Step 2: Move any backup files from sites-enabled to $BAK_DIR"
MOVED=0
shopt -s nullglob 2>/dev/null || true
for f in /etc/nginx/sites-enabled/*.bak* /etc/nginx/sites-enabled/*.backup*; do
  [[ -f "$f" ]] || continue
  name="$(basename "$f")"
  dest="${BAK_DIR}/${name}"
  sudo mv "$f" "$dest"
  log "Step 2: Moved $f -> $dest"
  MOVED=$((MOVED + 1))
done
shopt -u nullglob 2>/dev/null || true
[[ "$MOVED" -eq 0 ]] && log "Step 2: No backup files in sites-enabled (OK)"
log "Step 2: OK"

# --- Step 3: Create timestamped backup in backups/ before modifying ---
TS="$(date +%Y-%m-%d-%H%M)"
BAK="${BAK_DIR}/$(basename "$NGINX_SITE").bak.${TS}"
log "Step 3: Create backup: $BAK"
sudo cp -a "$NGINX_SITE" "$BAK"
log "Step 3: OK"

# --- Step 4: Apply new configuration ---
log "Step 4: Apply configuration change (proxy_pass -> ${LAB_PRIVATE_IP}:${OPENCLAW_PORT})"
BEFORE="$(sudo grep -cF "$OLD" "$NGINX_SITE" 2>/dev/null || echo 0)"
BEFORE_PUBLIC_8081="$(sudo grep -cF "$OLD_PUBLIC_8081" "$NGINX_SITE" 2>/dev/null || echo 0)"
# Replace public IP (8080 or 8081) with LAB private IP and correct port
if [[ "${BEFORE:-0}" -gt 0 ]]; then
  OLD_ESC="$(printf '%s' "$OLD" | sed 's/[\/&]/\\&/g')"
  if ! sudo sed -i '' "s|$OLD_ESC|$NEW|g" "$NGINX_SITE" 2>/dev/null; then
    sudo sed -i "s|$OLD_ESC|$NEW|g" "$NGINX_SITE"
  fi
  log "Step 4: Replaced public 52.77.216.100:8080 ($BEFORE occurrence(s)). OK"
elif [[ "${BEFORE_PUBLIC_8081:-0}" -gt 0 ]]; then
  OLD_PUBLIC_8081_ESC="$(printf '%s' "$OLD_PUBLIC_8081" | sed 's/[\/&]/\\&/g')"
  if ! sudo sed -i '' "s|$OLD_PUBLIC_8081_ESC|$NEW|g" "$NGINX_SITE" 2>/dev/null; then
    sudo sed -i "s|$OLD_PUBLIC_8081_ESC|$NEW|g" "$NGINX_SITE"
  fi
  log "Step 4: Replaced public 52.77.216.100:8081 ($BEFORE_PUBLIC_8081 occurrence(s)). OK"
elif [[ "${BEFORE:-0}" -eq 0 ]] && [[ "${BEFORE_PUBLIC_8081:-0}" -eq 0 ]]; then
  log "Step 4: No occurrences of old public upstream. Checking for common LAB upstream ports..."
  OLD2="proxy_pass http://${LAB_PRIVATE_IP}:8080/;"
  BEFORE2="$(sudo grep -cF "$OLD2" "$NGINX_SITE" 2>/dev/null || echo 0)"
  OLD3="proxy_pass http://${LAB_PRIVATE_IP}:8081/;"
  BEFORE3="$(sudo grep -cF "$OLD3" "$NGINX_SITE" 2>/dev/null || echo 0)"
  if [[ "${BEFORE2:-0}" -gt 0 ]]; then
    OLD2_ESC="$(printf '%s' "$OLD2" | sed 's/[\/&]/\\&/g')"
    if ! sudo sed -i '' "s|$OLD2_ESC|$NEW|g" "$NGINX_SITE" 2>/dev/null; then
      sudo sed -i "s|$OLD2_ESC|$NEW|g" "$NGINX_SITE"
    fi
    log "Step 4: Replaced LAB:8080 -> ${LAB_PRIVATE_IP}:${OPENCLAW_PORT} ($BEFORE2 occurrence(s)). OK"
  elif [[ "${BEFORE3:-0}" -gt 0 ]]; then
    OLD3_ESC="$(printf '%s' "$OLD3" | sed 's/[\/&]/\\&/g')"
    if ! sudo sed -i '' "s|$OLD3_ESC|$NEW|g" "$NGINX_SITE" 2>/dev/null; then
      sudo sed -i "s|$OLD3_ESC|$NEW|g" "$NGINX_SITE"
    fi
    log "Step 4: Replaced LAB:8081 -> ${LAB_PRIVATE_IP}:${OPENCLAW_PORT} ($BEFORE3 occurrence(s)). OK"
  else
    log "Step 4: Skipping replace (already correct or different)."
  fi
fi

# --- Step 4c: Sync every site file that defines /openclaw/ (including dashboard.conf) ---
# Public URL can 502 when curl to LAB works: the active server block may be in dashboard.conf, not default.
replace_openclaw_upstream_in_file "$NGINX_SITE"
for f in /etc/nginx/sites-enabled/*; do
  [[ -f "$f" ]] || continue
  [[ "$(readlink -f "$f" 2>/dev/null)" == "$(readlink -f "$NGINX_SITE" 2>/dev/null)" ]] && continue
  replace_openclaw_upstream_in_file "$f"
done

# --- Step 4b: Verify /openclaw/ block still present; if not, restore and exit ---
if ! sudo grep -qE 'location\s+(\^~\s+)?/openclaw/?' "$NGINX_SITE"; then
  log "Step 4b: FATAL: No 'location /openclaw/' block found after edit. Restoring backup and exiting."
  sudo cp -a "$BAK" "$NGINX_SITE"
  printf '\033[31mFATAL: Restored %s from backup. File missing location /openclaw/ block.\033[0m\n' "$NGINX_SITE"
  exit 3
fi

# --- Step 5: Validate with nginx -t; on failure restore and exit ---
log "Step 5: Validate configuration (nginx -t)"
if ! sudo nginx -t 2>&1; then
  log "Step 5: VALIDATION FAILED. Restoring previous configuration from backup."
  sudo cp -a "$BAK" "$NGINX_SITE"
  if sudo nginx -t 2>&1; then
    log "Step 5: Restore successful. Nginx config is back to previous state."
  else
    log "Step 5: ERROR: Restore succeeded but nginx -t still fails. Investigate manually."
  fi
  log "Rollback command: sudo cp -a '$BAK' '$NGINX_SITE' && sudo nginx -t && sudo systemctl reload nginx"
  exit 1
fi
log "Step 5: OK"

# --- Step 6: Reload nginx ---
log "Step 6: Reload nginx"
sudo systemctl reload nginx
log "Step 6: OK"

log "Done. Verifying..."
echo ""
curl -sS -m 5 -I "http://${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/" 2>/dev/null | head -n 5 || true
echo ""
curl -sS -m 8 -I https://dashboard.hilovivo.com/openclaw/ 2>/dev/null | head -n 8 || true
echo ""
log "Rollback if needed: sudo cp -a '$BAK' '$NGINX_SITE' && sudo nginx -t && sudo systemctl reload nginx"
