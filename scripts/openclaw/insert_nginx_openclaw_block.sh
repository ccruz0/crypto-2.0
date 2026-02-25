#!/usr/bin/env bash
# Insert the OpenClaw Nginx proxy block into the Dashboard 443 server config.
# Run ON the Dashboard host (Nginx for dashboard.hilovivo.com). Requires sudo.
#
# Usage:
#   sudo ./scripts/openclaw/insert_nginx_openclaw_block.sh <OPENCLAW_PRIVATE_IP>
#
# Preconditions:
#   - This runs on the Dashboard host (server running Nginx for dashboard.hilovivo.com)
#   - The target config must contain a server block with "listen 443"
#   - <OPENCLAW_PRIVATE_IP> must be reachable from this host
#
# Post-check:
#   curl -I https://dashboard.hilovivo.com/openclaw     -> 301
#   curl -I https://dashboard.hilovivo.com/openclaw/    -> 401
#
# If you see:
#   404 -> block not inserted in correct 443 server
#   504 -> upstream not reachable (see OPENCLAW_504_UPSTREAM_DIAGNOSIS.md)
#
# If the block already exists (location ^~ /openclaw/), exits without change.

set -e
OPENCLAW_IP="${1:-172.31.3.214}"
CONFIG=$(readlink -f /etc/nginx/sites-enabled/default)

# Ensure we're editing a config that has HTTPS (server 443). Do not insert into port-80-only configs.
if ! grep -q 'listen.*443' "$CONFIG" 2>/dev/null; then
  echo "ERROR: $CONFIG does not contain 'listen 443'. Refusing to insert (must target HTTPS server block)."
  exit 1
fi

if ! grep -q 'location ^~ /openclaw/' "$CONFIG" 2>/dev/null; then
  echo "Block not found. Inserting OpenClaw block (upstream $OPENCLAW_IP) into $CONFIG (443 server)"
else
  echo "Block already present in $CONFIG. Exiting."
  exit 0
fi

BACKUP="${CONFIG}.bak.$(date +%s)"
sudo cp -a "$CONFIG" "$BACKUP"
echo "Backup: $BACKUP"

TMPBLOCK=$(mktemp)
trap 'rm -f "$TMPBLOCK"' EXIT
cat << BLOCK > "$TMPBLOCK"
    location = /openclaw {
        return 301 /openclaw/;
    }

    location ^~ /openclaw/ {
        auth_basic "OpenClaw";
        auth_basic_user_file /etc/nginx/.htpasswd_openclaw;

        proxy_pass http://${OPENCLAW_IP}:8080/;

        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_cache_bypass \$http_upgrade;

        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        proxy_connect_timeout 30s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;

        proxy_hide_header X-Frame-Options;
        add_header Content-Security-Policy "frame-ancestors 'self' https://dashboard.hilovivo.com" always;
        add_header X-Frame-Options "" always;
    }

BLOCK

# Insert block before the first "location / {" in the file (in dashboard.conf this is inside the server { listen 443 } block)
sudo awk -v blockfile="$TMPBLOCK" '
  /location \/ \{/ && !done {
    while ((getline line < blockfile) > 0) print line
    close(blockfile)
    done = 1
  }
  { print }
' "$CONFIG" > "${CONFIG}.new" && sudo mv "${CONFIG}.new" "$CONFIG"

sudo nginx -t && sudo systemctl reload nginx
echo "Done. Reloaded nginx. Test: curl -I https://dashboard.hilovivo.com/openclaw/"
