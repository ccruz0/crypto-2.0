#!/usr/bin/env bash
# Set GITHUB_TOKEN in secrets/runtime.env and restart backend for deploy trigger.
# Run from repo root.
#
# Option 1 (popup): GUI dialog
#   python3 scripts/set_github_token_popup.py
#
# Option 2 (non-interactive): pass token via env
#   GITHUB_TOKEN=ghp_xxx ./scripts/set_github_token_for_deploy.sh
#
# Option 3 (interactive): script will prompt in terminal
#   ./scripts/set_github_token_for_deploy.sh

set -e
cd "$(dirname "$0")/.."

if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "Paste your GitHub PAT (ghp_...):"
  read -s GITHUB_TOKEN
  echo ""
fi

if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "Error: No token provided." >&2
  exit 1
fi

mkdir -p secrets

if grep -q "^GITHUB_TOKEN=" secrets/runtime.env 2>/dev/null; then
  if [[ "$(uname)" == "Darwin" ]]; then
    sed -i '' "s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$GITHUB_TOKEN|" secrets/runtime.env
  else
    sed -i "s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$GITHUB_TOKEN|" secrets/runtime.env
  fi
else
  echo "GITHUB_TOKEN=$GITHUB_TOKEN" >> secrets/runtime.env
fi

echo "Token written to secrets/runtime.env"

docker compose --profile aws restart backend-aws

echo "Backend restarted."
echo "Deploy trigger should now work."
