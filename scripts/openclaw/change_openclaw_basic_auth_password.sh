#!/usr/bin/env bash
# Run from your Mac. Connects to PROD and runs htpasswd for OpenClaw Basic Auth.
# You will be prompted for the new password on the remote side (typed securely, not logged).
#
# Usage:
#   ./scripts/openclaw/change_openclaw_basic_auth_password.sh
#
# Optional: OPENCLAW_AUTH_USER=admin (default). SSH key and host from env or defaults below.

set -euo pipefail
SSH_KEY="${SSH_KEY:-$HOME/.ssh/atp-rebuild-2026.pem}"
PROD_HOST="${PROD_HOST:-ubuntu@52.220.32.147}"
HTPASSWD_FILE="/etc/nginx/.htpasswd_openclaw"
USER="${OPENCLAW_AUTH_USER:-admin}"

if [[ ! -f "$SSH_KEY" ]]; then
  echo "ERROR: SSH key not found: $SSH_KEY"
  exit 1
fi

echo "Connecting to PROD and updating Basic Auth user: $USER"
echo "File on server: $HTPASSWD_FILE"
echo "You will be prompted for the NEW password (and confirmation) on the remote server."
echo ""

# Check if file exists; if not, use -c to create
ssh -i "$SSH_KEY" "$PROD_HOST" "sudo test -f $HTPASSWD_FILE" 2>/dev/null && USE_C="" || USE_C="-c"
ssh -t -i "$SSH_KEY" "$PROD_HOST" "sudo htpasswd $USE_C $HTPASSWD_FILE $USER"

echo ""
echo "Verifying..."
ssh -i "$SSH_KEY" "$PROD_HOST" "sudo cat $HTPASSWD_FILE | sed 's/:.*/:***/'"
echo ""
echo "Test endpoint (expect 401):"
curl -sI https://dashboard.hilovivo.com/openclaw/ | head -5
echo ""
echo "Test in browser: https://dashboard.hilovivo.com/openclaw/ — user: $USER"
