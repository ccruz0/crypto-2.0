#!/usr/bin/env bash
# Test GitHub workflow_dispatch. Uses host curl with token from secrets/runtime.env.
# Usage: ./scripts/test_deploy_dispatch.sh

cd "$(dirname "$0")/.."

GITHUB_TOKEN=$(grep '^GITHUB_TOKEN=' secrets/runtime.env 2>/dev/null | cut -d= -f2-)
if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "ERROR: GITHUB_TOKEN not set in secrets/runtime.env"
  exit 1
fi

echo "Dispatching workflow: ccruz0/crypto-2.0 deploy_session_manager.yml ref=main"
echo "Token present: yes (length ${#GITHUB_TOKEN})"

curl -sS -w "\nHTTP_STATUS:%{http_code}\n" -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/ccruz0/crypto-2.0/actions/workflows/deploy_session_manager.yml/dispatches" \
  -d '{"ref":"main"}'
