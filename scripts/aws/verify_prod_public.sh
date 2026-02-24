#!/usr/bin/env bash
# Verify PROD (dashboard) is reachable from this machine.
# Usage: ./scripts/aws/verify_prod_public.sh [BASE_URL]
# Default BASE_URL: https://dashboard.hilovivo.com

set -e
BASE_URL="${1:-https://dashboard.hilovivo.com}"
HEALTH_URL="${BASE_URL%/}/api/health"

echo "Checking PROD: $HEALTH_URL"
HTTP_CODE=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 10 "$HEALTH_URL" 2>/dev/null || echo "000")

if [ "$HTTP_CODE" = "200" ]; then
  echo "OK (HTTP $HTTP_CODE)"
  exit 0
else
  echo "FAIL (HTTP $HTTP_CODE)"
  exit 1
fi
