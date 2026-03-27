#!/usr/bin/env bash
# Deploy OpenClaw reverse proxy block into production Nginx (dashboard.hilovivo.com).
# Server: Ubuntu 52.220.32.147. Inserts block before "location /" in the dashboard server block.
# Backups go to /etc/nginx/backups/ (not sites-enabled) to avoid "duplicate default server".
#
# Usage (from repo root):
#   cd ~/crypto-2.0
#   ./scripts/openclaw/deploy_openclaw_nginx_prod.sh
#
# Dry-run (no remote changes, no reload):
#   DRY_RUN=1 ./scripts/openclaw/deploy_openclaw_nginx_prod.sh

set -e

DRY_RUN="${DRY_RUN:-0}"
SSH_KEY="${HOME}/.ssh/atp-rebuild-2026.pem"
HOST="ubuntu@52.220.32.147"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BLOCK_FILE="${REPO_ROOT}/scripts/openclaw/openclaw_nginx_block.txt"

if [[ ! -f "$SSH_KEY" ]]; then
  echo "SSH key not found: $SSH_KEY"
  exit 1
fi
if [[ ! -f "$BLOCK_FILE" ]]; then
  echo "Block file not found: $BLOCK_FILE"
  exit 1
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] No remote files will be modified; nginx will not be reloaded."
  echo ""
fi

echo "=== 1) Locate active Nginx config (server_name dashboard.hilovivo.com) ==="
# Only consider enabled sites (sites-enabled), resolve symlinks, exclude backups (*.bak.*, *.backup, *~)
CONFIG_LIST=$(ssh -o StrictHostKeyChecking=accept-new -i "$SSH_KEY" "$HOST" '
  for f in /etc/nginx/sites-enabled/*; do
    [ -e "$f" ] || continue
    real=$(readlink -f "$f" 2>/dev/null || echo "$f")
    case "$real" in *.bak.*|*.backup|*~) continue ;; esac
    grep -q "server_name dashboard.hilovivo.com" "$real" 2>/dev/null && echo "$real"
  done | sort -u
' || true)
CONFIG_COUNT=$(echo "$CONFIG_LIST" | grep -c . 2>/dev/null); CONFIG_COUNT=${CONFIG_COUNT:-0}

if [[ "$CONFIG_COUNT" -eq 0 ]]; then
  echo "Error: No active config (sites-enabled) found with server_name dashboard.hilovivo.com"
  exit 1
fi
if [[ "$CONFIG_COUNT" -gt 1 ]]; then
  echo "Error: More than one active config matches. Refusing to choose. Candidates:"
  echo "$CONFIG_LIST"
  exit 1
fi

CONFIG_PATH=$(echo "$CONFIG_LIST" | head -1)
echo "Config file (active vhost): $CONFIG_PATH"

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] Would use: $CONFIG_PATH"
fi

echo ""
echo "=== 2) Check if OpenClaw block already present (idempotent) ==="
HAS_PROXY=$(ssh -i "$SSH_KEY" "$HOST" "grep -c 'location ^~ /openclaw/' '$CONFIG_PATH' 2>/dev/null || true")
HAS_REDIRECT=$(ssh -i "$SSH_KEY" "$HOST" "grep -c 'location = /openclaw' '$CONFIG_PATH' 2>/dev/null || true")
if [[ "$HAS_PROXY" -gt 0 ]] || [[ "$HAS_REDIRECT" -gt 0 ]]; then
  echo "OpenClaw block (redirect or proxy) already present in $CONFIG_PATH. Skipping insert."
  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY_RUN] Would skip insert and exit."
    exit 0
  fi
  ssh -i "$SSH_KEY" "$HOST" "sudo nginx -t && sudo systemctl reload nginx"
  echo ""
  echo "=== Verify ==="
  curl -sI "https://dashboard.hilovivo.com/openclaw/"
  exit 0
fi

echo ""
echo "=== 3) Verify 'location / {' exists in config (safety) ==="
HAS_LOCATION_ROOT=$(ssh -i "$SSH_KEY" "$HOST" "grep -cE '^[[:space:]]*location / \\{' '$CONFIG_PATH' 2>/dev/null || true")
if [[ "$HAS_LOCATION_ROOT" -eq 0 ]]; then
  echo "Error: No line matching 'location / {' found in $CONFIG_PATH. Refusing to insert."
  exit 1
fi
echo "Found 'location / {' in $CONFIG_PATH — OK."

if [[ "$DRY_RUN" == "1" ]]; then
  echo "[DRY_RUN] Would: copy block to server, create timestamped backup, insert block before first 'location / {', then run nginx -t and reload."
  echo "[DRY_RUN] Would ensure /etc/nginx/.htpasswd_openclaw exists (create if missing)."
  echo ""
  echo "[DRY_RUN] No changes made. Exiting."
  exit 0
fi

echo "Copying block file to server..."
scp -i "$SSH_KEY" "$BLOCK_FILE" "$HOST:/tmp/openclaw_nginx_block.txt"

echo ""
echo "=== 4) Insert block before 'location /' and backup ==="
# Backup to a dir nginx does NOT include (avoids "duplicate default server" when config lives in sites-enabled)
ssh -i "$SSH_KEY" "$HOST" bash -s -- "$CONFIG_PATH" << 'REMOTE'
set -e
CONFIG="$1"
BACKUP_DIR="/etc/nginx/backups"
sudo mkdir -p "$BACKUP_DIR"
BACKUP="${BACKUP_DIR}/$(basename "$CONFIG").bak.$(date +%Y%m%d%H%M%S)"
sudo cp "$CONFIG" "$BACKUP"
echo "Backup: $BACKUP"
sudo awk '
  /^[[:space:]]*location \/ \{/ && !inserted {
    while ((getline line < "/tmp/openclaw_nginx_block.txt") > 0) print line
    inserted = 1
  }
  { print }
' "$CONFIG" > /tmp/nginx_openclaw_new
sudo mv /tmp/nginx_openclaw_new "$CONFIG"
sudo rm -f /tmp/openclaw_nginx_block.txt
echo "Block inserted."
REMOTE

echo ""
echo "=== 5) Basic Auth file (create if missing) ==="
if ! ssh -i "$SSH_KEY" "$HOST" 'command -v htpasswd >/dev/null 2>&1'; then
  echo "htpasswd not found on server. Install with: sudo apt-get update -qq && sudo apt-get install -y apache2-utils"
  echo "Then re-run this script, or create the file manually: sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw"
  exit 1
fi
ssh -i "$SSH_KEY" "$HOST" 'test -f /etc/nginx/.htpasswd_openclaw' || {
  echo "Creating /etc/nginx/.htpasswd_openclaw (enter password when prompted)..."
  ssh -t -i "$SSH_KEY" "$HOST" 'sudo htpasswd -c /etc/nginx/.htpasswd_openclaw openclaw'
  ssh -i "$SSH_KEY" "$HOST" 'sudo chmod 600 /etc/nginx/.htpasswd_openclaw'
}

echo ""
echo "=== 6) Validate config and reload (only if nginx -t passes) ==="
if ! ssh -i "$SSH_KEY" "$HOST" "sudo nginx -t"; then
  echo "Error: nginx -t failed. Not reloading. Restore from backup if needed."
  echo "If error was 'duplicate default server', remove any .bak from sites-enabled: sudo rm -f /etc/nginx/sites-enabled/*.bak.*"
  exit 1
fi
ssh -i "$SSH_KEY" "$HOST" "sudo systemctl reload nginx"
echo "Syntax test: OK. Nginx reloaded."

echo ""
echo "=== 7) Final result ==="
echo "Exact file modified: $CONFIG_PATH"
echo ""
echo "First 20 lines of inserted block:"
head -20 "$BLOCK_FILE"
echo ""
echo "curl -I https://dashboard.hilovivo.com/openclaw/"
CURL_OUT=$(curl -sI "https://dashboard.hilovivo.com/openclaw/")
echo "$CURL_OUT"

if echo "$CURL_OUT" | head -1 | grep -q "401"; then
  echo ""
  echo "Expected without auth: 401 Unauthorized — OK. With auth (browser): expect 200."
  echo ""
  echo "Done."
  exit 0
fi

# Phase 2: HTTPS returned 308 or 404 → block likely only in server 80; insert into server 443
if echo "$CURL_OUT" | head -1 | grep -qE "308|404"; then
  echo ""
  echo "HTTPS returned $(echo "$CURL_OUT" | head -1). Block may be only in server 80. Inserting into server 443..."
  scp -i "$SSH_KEY" "$BLOCK_FILE" "$HOST:/tmp/openclaw_nginx_block.txt"
  ssh -i "$SSH_KEY" "$HOST" bash -s -- "$CONFIG_PATH" << 'REMOTE_PHASE2'
set -e
CONFIG="$1"
# Find first "location / {" after "listen 443" (that is the 443 server block)
LINE=$(sudo awk '/listen.*443/ { start=NR } start && /^[[:space:]]*location[[:space:]]+\/[[:space:]]*\{/ { print NR; exit }' "$CONFIG" 2>/dev/null || true)
if [[ -z "$LINE" ]]; then
  echo "Could not find location / in 443 block. Paste server block: sudo nginx -T 2>/dev/null | sed -n '/server_name dashboard.hilovivo.com/,/^}/p'"
  exit 1
fi
# Insert block before that line
sudo awk -v line="$LINE" '
  NR==line { while ((getline < "/tmp/openclaw_nginx_block.txt") > 0) print }
  { print }
' "$CONFIG" > /tmp/nginx_openclaw_443_new
sudo mv /tmp/nginx_openclaw_443_new "$CONFIG"
sudo rm -f /tmp/openclaw_nginx_block.txt
echo "Block inserted into 443 server (before line $LINE)."
REMOTE_PHASE2
  if ! ssh -i "$SSH_KEY" "$HOST" "sudo nginx -t"; then
    echo "Error: nginx -t failed after 443 insert. Restore from backup."
    exit 1
  fi
  ssh -i "$SSH_KEY" "$HOST" "sudo systemctl reload nginx"
  echo "Reloaded. Verifying HTTPS..."
  CURL_OUT=$(curl -sI "https://dashboard.hilovivo.com/openclaw/")
  echo "$CURL_OUT"
  if echo "$CURL_OUT" | head -1 | grep -q "401"; then
    echo ""
    echo "HTTPS now returns 401 — OK."
    echo ""
    echo "Done."
    exit 0
  fi
  echo ""
  echo "HTTPS still not 401. Paste server block for manual fix: sudo nginx -T 2>/dev/null | sed -n '/server_name dashboard.hilovivo.com/,/^}/p'"
  exit 1
fi

echo ""
echo "Unexpected first line (expected 401 without auth). Check config and htpasswd."
exit 1
