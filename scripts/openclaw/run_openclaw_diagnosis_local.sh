#!/usr/bin/env bash
# OpenClaw diagnostics from your machine: curl public URLs + optional SSM.
# No SSH or server access required for the curl part.
#
# Usage: ./scripts/openclaw/run_openclaw_diagnosis_local.sh
# Optional: OPENCLAW_BASE_URL=https://dashboard.hilovivo.com SKIP_SSM=1 ./scripts/openclaw/run_openclaw_diagnosis_local.sh

set -e

OPENCLAW_BASE_URL="${OPENCLAW_BASE_URL:-https://dashboard.hilovivo.com}"
SKIP_SSM="${SKIP_SSM:-}"
OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

echo "=== OpenClaw diagnosis (local curl + optional SSM) ==="
echo "Base URL: $OPENCLAW_BASE_URL"
echo ""

# --- 1) Curl /openclaw/ ---
echo "--- 1) GET $OPENCLAW_BASE_URL/openclaw/ ---"
HTTP_OPENCLAW=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 15 "$OPENCLAW_BASE_URL/openclaw/" 2>/dev/null || echo "000")
echo "HTTP status: $HTTP_OPENCLAW"

# --- 2) Curl /openclaw/ws ---
echo ""
echo "--- 2) GET $OPENCLAW_BASE_URL/openclaw/ws ---"
HTTP_WS=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 10 "$OPENCLAW_BASE_URL/openclaw/ws" 2>/dev/null || echo "000")
echo "HTTP status: $HTTP_WS"

# --- 3) Optional SSM ---
SSM_STATUS=""
if [[ -z "$SKIP_SSM" ]] && command -v aws &>/dev/null; then
  echo ""
  echo "--- 3) SSM (Dashboard PROD) ---"
  DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-i-087953603011543c5}"
  AWS_REGION="${AWS_REGION:-ap-southeast-1}"
  SSM_STATUS=$(aws ssm describe-instance-information --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$DASHBOARD_INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
  echo "Dashboard ($DASHBOARD_INSTANCE_ID) PingStatus: ${SSM_STATUS:-NotFound}"
else
  if [[ -n "$SKIP_SSM" ]]; then echo ""; echo "--- 3) SSM skipped (SKIP_SSM=1) ---"; fi
fi

# --- Summary and classification ---
echo ""
echo "=== Summary ==="

if [[ "$HTTP_OPENCLAW" == "404" ]]; then
  echo "Classification: A. Nginx block missing (404 on /openclaw/)"
  echo "NEXT ACTION: On PROD run: sudo bash scripts/openclaw/insert_nginx_openclaw_block.sh <LAB_PRIVATE_IP>"
  echo "             Then: sudo nginx -t && sudo systemctl reload nginx"
  exit 1
fi

if [[ "$HTTP_OPENCLAW" == "504" ]] || [[ "$HTTP_OPENCLAW" == "502" ]] || [[ "$HTTP_OPENCLAW" == "000" ]]; then
  echo "Classification: B. Upstream unreachable ($HTTP_OPENCLAW)"
  echo "NEXT ACTION: Check LAB is running OpenClaw (systemctl status openclaw, port ${OPENCLAW_PORT})."
  echo "             On PROD ensure nginx upstream IP/port match LAB."
  exit 1
fi

if [[ "$HTTP_OPENCLAW" == "401" ]] || [[ "$HTTP_OPENCLAW" == "200" ]] || [[ "$HTTP_OPENCLAW" == "302" ]]; then
  echo "Proxy and upstream: OK (HTTP $HTTP_OPENCLAW — auth or redirect as expected)"
  if [[ "$HTTP_WS" == "401" ]] || [[ "$HTTP_WS" == "101" ]] || [[ "$HTTP_WS" == "200" ]]; then
    echo "WebSocket endpoint: OK (HTTP $HTTP_WS)"
    echo "Classification: E. Everything appears healthy (from public URLs)"
    echo "NEXT ACTION: Open $OPENCLAW_BASE_URL/openclaw/ in browser; use Basic auth if prompted."
    if [[ "$SSM_STATUS" == "ConnectionLost" ]]; then
      echo "Note: SSM to Dashboard is ConnectionLost. To run server-side checks see docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md"
    fi
    exit 0
  fi
  if [[ "$HTTP_WS" != "401" ]] && [[ "$HTTP_WS" != "101" ]] && [[ "$HTTP_WS" != "200" ]]; then
    echo "WebSocket endpoint: HTTP $HTTP_WS (check nginx proxy for /openclaw/ws)"
    echo "Classification: D. WebSocket misconfiguration (or upstream WS not listening)"
    echo "NEXT ACTION: Ensure nginx proxies /openclaw/ws to LAB:${OPENCLAW_PORT} with Upgrade/Connection headers. In app use wss:// same-origin, not ws://localhost."
    exit 1
  fi
fi

echo "Classification: Unclear (openclaw=$HTTP_OPENCLAW ws=$HTTP_WS)"
echo "NEXT ACTION: Run manual commands on PROD and LAB (see docs/openclaw/OPENCLAW_AT_DASHBOARD_QUICK.md)"
exit 1
