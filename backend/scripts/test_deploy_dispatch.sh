#!/usr/bin/env bash
# Test GitHub workflow_dispatch from inside backend-aws container.
# Run on host: docker compose --profile aws exec backend-aws /app/scripts/test_deploy_dispatch.sh
# Or run curl manually after exec'ing into the container.

set -e
GITHUB_TOKEN="${GITHUB_TOKEN:-$(grep '^GITHUB_TOKEN=' /app/secrets/runtime.env 2>/dev/null | cut -d= -f2-)}"
REPO="${GITHUB_REPOSITORY:-ccruz0/crypto-2.0}"
WORKFLOW="${DEPLOY_WORKFLOW_FILE:-deploy_session_manager.yml}"
REF="${REF:-main}"

if [[ -z "$GITHUB_TOKEN" ]]; then
  echo "ERROR: GITHUB_TOKEN not set. Add to secrets/runtime.env and force-recreate backend-aws."
  exit 1
fi

echo "Dispatching workflow: $REPO $WORKFLOW ref=$REF"
echo "Token present: yes (length ${#GITHUB_TOKEN})"

curl -sS -w "\nHTTP_STATUS:%{http_code}\n" -X POST \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$REPO/actions/workflows/$WORKFLOW/dispatches" \
  -d "{\"ref\":\"$REF\"}"
