#!/usr/bin/env bash
# Run post-deploy smoke check for the task currently in "deploying".
# Uses backend API POST /api/agent/run-smoke-check (no body = first deploying task).
# Set API_BASE_URL to your backend (e.g. https://dashboard.hilovivo.com) if not local.
set -e
BASE="${API_BASE_URL:-http://localhost:8002}"
TASK_ID="${1:-}"
echo "Running smoke check via $BASE (task_id=${TASK_ID:-auto})..."
if [ -n "$TASK_ID" ]; then
  BODY="{\"task_id\": \"$TASK_ID\"}"
else
  BODY="{}"
fi
curl -sS -X POST "$BASE/api/agent/run-smoke-check" \
  -H "Content-Type: application/json" \
  -d "$BODY" | jq . 2>/dev/null || cat
