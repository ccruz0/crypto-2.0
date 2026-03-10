#!/usr/bin/env bash
# Run on the dashboard server (or from a host that can reach dashboard.hilovivo.com).
# Verifies OpenClaw UI proxy: auth, CSP, and that LAB is not needed to be public.
set -euo pipefail
BASE="${BASE_URL:-https://dashboard.hilovivo.com}"

echo "=== 1) /openclaw/ requires auth or returns 200 ==="
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/openclaw/")
if [ "$STATUS" = "401" ]; then
  echo "OK: 401 Unauthorized (Basic Auth required)."
elif [ "$STATUS" = "200" ]; then
  echo "OK: 200 (already cached auth or auth disabled)."
else
  echo "WARN: Got $STATUS (expected 401 or 200)."
fi

echo ""
echo "=== 2) Response headers for /openclaw/ (CSP frame-ancestors) ==="
curl -sI "$BASE/openclaw/" | grep -iE "content-security-policy|x-frame-options" || true

echo ""
echo "=== 3) Optional: check /openclaw/api/ if it exists ==="
STATUS_API=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/openclaw/api/" 2>/dev/null || echo "000")
echo "/openclaw/api/ → $STATUS_API (should be 401/404/200, not open without auth)."

echo ""
echo "Done. Ensure LAB port 8080 is not open to 0.0.0.0/0 (Security Group)."
