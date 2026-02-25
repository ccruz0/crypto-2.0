#!/usr/bin/env bash
# Create OpenClaw token file on LAB. You only need to paste your GitHub PAT when prompted.
#
# Run on the LAB instance (e.g. via Session Manager), with sudo:
#   sudo ./scripts/openclaw/setup_openclaw_token.sh
#
# Or from any directory:
#   sudo bash /home/ubuntu/automated-trading-platform/scripts/openclaw/setup_openclaw_token.sh
#
# Token: GitHub → Settings → Developer settings → Fine-grained tokens →
#        Contents (R/W), Pull requests (R/W). Copy the token, then paste here (nothing will show).

set -e
TOKEN_FILE="${1:-/home/ubuntu/secrets/openclaw_token}"

echo "OpenClaw token setup"
echo "--------------------"
echo "Paste your GitHub fine-grained PAT below (input is hidden). Press Enter when done."
echo ""

# Read token without echoing
read -r -s TOKEN
echo ""

if [ -z "$TOKEN" ]; then
  echo "Error: no token entered. Exiting."
  exit 1
fi

SECRETS_DIR="$(dirname "$TOKEN_FILE")"
mkdir -p "$SECRETS_DIR"
echo -n "$TOKEN" > "$TOKEN_FILE"
chown ubuntu:ubuntu "$TOKEN_FILE"
chmod 600 "$TOKEN_FILE"

echo "OK: Token written to $TOKEN_FILE (owner ubuntu, mode 600)."
echo "Verify: sudo -u ubuntu test -r $TOKEN_FILE && echo 'Readable by ubuntu'"
