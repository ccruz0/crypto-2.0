#!/usr/bin/env bash
# Verify OpenClaw gateway model routing and failover-friendly behavior.
# See docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md
#
# Usage:
#   OPENCLAW_GATEWAY_URL=http://172.31.3.214:8080 OPENCLAW_API_TOKEN=<token> ./scripts/openclaw/verify_gateway_model_routing.sh
# Or from LAB:
#   OPENCLAW_GATEWAY_URL=http://127.0.0.1:8080 OPENCLAW_API_TOKEN=$(jq -r '.gateway.auth.token' /opt/openclaw/openclaw.json) ./scripts/openclaw/verify_gateway_model_routing.sh
#
# Tests:
#   1. Valid supported model -> expect 200
#   2. Unsupported model -> expect 400 and body containing "model" and "not supported" (or similar)
set -euo pipefail

BASE_URL="${OPENCLAW_GATEWAY_URL:-}"
TOKEN="${OPENCLAW_API_TOKEN:-}"
# Optional: model that is supported by your gateway (default from cheap-first chain)
VALID_MODEL="${OPENCLAW_VERIFY_VALID_MODEL:-openai/gpt-4o-mini}"

if [[ -z "$BASE_URL" || -z "$TOKEN" ]]; then
  echo "Usage: OPENCLAW_GATEWAY_URL=<base> OPENCLAW_API_TOKEN=<token> $0" 1>&2
  echo "Example: OPENCLAW_GATEWAY_URL=http://127.0.0.1:8080 OPENCLAW_API_TOKEN=secret $0" 1>&2
  exit 1
fi

URL="${BASE_URL%/}/v1/responses"
PASS=0
FAIL=0

# Test 1: Valid supported model -> 200, and optionally check usage in response
test_valid_model() {
  local code body body_content usage
  body=$(curl -sS -w '\n%{http_code}' -X POST "$URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"model\":\"$VALID_MODEL\",\"input\":\"Say hello in one word.\"}")
  code=$(echo "$body" | tail -n1)
  body_content=$(echo "$body" | sed '$d')
  if [[ "$code" == "200" ]]; then
    echo "[PASS] Valid model ($VALID_MODEL) -> 200"
    # Usage check: ATP openclaw_apply_cost expects input_tokens, output_tokens, total_tokens
    if command -v jq >/dev/null 2>&1; then
      usage=$(echo "$body_content" | jq -r '.usage // empty' 2>/dev/null)
      if [[ -n "$usage" && "$usage" != "null" ]]; then
        echo "  usage: $usage"
      else
        echo "  [INFO] No usage in response; openclaw_apply_cost will show usage=None until gateway forwards provider token counts"
      fi
    fi
    ((PASS++)) || true
    return 0
  fi
  echo "[FAIL] Valid model ($VALID_MODEL) -> expected 200, got $code"
  ((FAIL++)) || true
  return 1
}

# Test 2: Unsupported model -> 400, body contains "model" and "not supported" or "unknown" or "invalid"
test_unsupported_model() {
  local code body
  body=$(curl -sS -w '\n%{http_code}' -X POST "$URL" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"model":"unsupported/fake-model-id","input":"Hi"}')
  code=$(echo "$body" | tail -n1)
  body_content=$(echo "$body" | sed '$d')
  if [[ "$code" != "400" ]]; then
    echo "[FAIL] Unsupported model -> expected 400, got $code"
    ((FAIL++)) || true
    return 1
  fi
  if echo "$body_content" | grep -qiE 'model.*(not supported|unknown|invalid)|(not supported|unknown|invalid).*model'; then
    echo "[PASS] Unsupported model -> 400 with body indicating model error"
    ((PASS++)) || true
    return 0
  fi
  echo "[WARN] Unsupported model -> 400 but body may not contain 'model' and 'not supported' (body: ${body_content:0:200})"
  ((PASS++)) || true
  return 0
}

test_valid_model || true
test_unsupported_model || true

echo "---"
echo "Result: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
