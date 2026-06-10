#!/usr/bin/env bash
# Monitor GitHub App cutover health on PROD EC2 (run from repo root).
# Never prints secret values.
#
# Usage:
#   bash scripts/aws/monitor_github_app_cutover.sh

set -uo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

PING_URL="http://127.0.0.1:8002/ping_fast"
READY_URL="http://127.0.0.1:8002/api/health/ready"
CANARY_PING_URL="http://127.0.0.1:8003/ping_fast"
CANARY_READY_URL="http://127.0.0.1:8003/api/health/ready"
LOG_TAIL="${LOG_TAIL:-200}"

FAIL_REASONS=()
EXCHANGE_WARN=no
OVERALL_PASS=yes

note_fail() {
  FAIL_REASONS+=("$1")
  OVERALL_PASS=no
}

check_service_container() {
  local service="$1"
  local cid running health name

  cid="$(docker compose --profile aws ps -q "$service" 2>/dev/null | head -1 || true)"
  if [[ -z "$cid" ]]; then
    echo "  $service: NOT RUNNING"
    note_fail "$service not running"
    return 1
  fi

  running="$(docker inspect "$cid" --format='{{.State.Running}}' 2>/dev/null || echo false)"
  health="$(docker inspect "$cid" --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || echo unknown)"
  name="$(docker inspect "$cid" --format='{{.Name}}' 2>/dev/null | sed 's|^/||')"

  if [[ "$running" != "true" ]]; then
    echo "  $service ($name): not running"
    note_fail "$service not running"
    return 1
  fi

  case "$health" in
    healthy)
      echo "  $service ($name): running, healthy"
      ;;
    starting)
      echo "  $service ($name): running, health=starting"
      note_fail "$service health starting"
      ;;
    unhealthy)
      echo "  $service ($name): running, UNHEALTHY"
      note_fail "$service unhealthy"
      ;;
    none)
      echo "  $service ($name): running (no docker healthcheck status)"
      ;;
    *)
      echo "  $service ($name): running, health=$health"
      if [[ "$health" != "healthy" ]]; then
        note_fail "$service health=$health"
      fi
      ;;
  esac
  return 0
}

check_http_health() {
  local label="$1"
  local ping_url="$2"
  local ready_url="$3"
  local ping_status ready_status

  ping_status="$(curl -s -m 5 "$ping_url" 2>/dev/null || true)"
  ready_status="$(curl -s -m 10 "$ready_url" 2>/dev/null || true)"

  if echo "$ping_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "  $label /ping_fast: ok"
  else
    echo "  $label /ping_fast: FAIL"
    note_fail "$label /ping_fast not ok"
  fi

  if echo "$ready_status" | grep -q '"status"[[:space:]]*:[[:space:]]*"ready"'; then
    echo "  $label /api/health/ready: ready"
  else
    echo "  $label /api/health/ready: FAIL"
    note_fail "$label /api/health/ready not ready"
  fi
}

inspect_backend_logs() {
  local service="$1"
  local logs patterns exchange_patterns

  echo "  -- $service (last ${LOG_TAIL} lines) --"
  logs="$(docker compose --profile aws logs "$service" --tail="$LOG_TAIL" 2>/dev/null || true)"
  if [[ -z "$logs" ]]; then
    echo "    (no logs)"
    return 0
  fi

  patterns='failed to mint|GitHub API auth unavailable|auth_method=none|legacy_pat|PermissionError'
  if echo "$logs" | grep -Eiq "$patterns"; then
    echo "    GitHub auth log warnings:"
    echo "$logs" | grep -Ei "$patterns" | tail -20 | sed 's/^/      /'
    note_fail "$service logs contain GitHub auth warnings"
  else
    echo "    GitHub auth log warnings: none"
  fi

  exchange_warn_patterns='API credentials not configured|Authentication failure|40101|Missing EXCHANGE_CUSTOM_API_KEY|Missing EXCHANGE_CUSTOM_API_SECRET|not allowlisted|authentication failed|Crypto\.com API authentication'
  exchange_hits="$(echo "$logs" | grep -Ei "$exchange_warn_patterns" | grep -vi 'password authentication failed' || true)"
  if [[ -n "$exchange_hits" ]]; then
    echo "    Exchange credential/auth warnings:"
    echo "$exchange_hits" | tail -10 | sed 's/^/      /'
    EXCHANGE_WARN=yes
  else
    echo "    Exchange credential/auth warnings: none"
  fi
}

echo "== GitHub App cutover monitor =="
echo "repo: $ROOT_DIR"
echo "time_utc: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo

echo "== 1. Container status =="
check_service_container backend-aws || true
check_service_container backend-aws-canary || true
echo

echo "== 2. HTTP health probes =="
check_http_health "backend-aws" "$PING_URL" "$READY_URL"
check_http_health "backend-aws-canary" "$CANARY_PING_URL" "$CANARY_READY_URL"
echo

echo "== 3. Cutover readiness (verify_github_app_cutover_ready.sh) =="
VERIFY_OUT=""
VERIFY_OUT="$(bash scripts/aws/verify_github_app_cutover_ready.sh 2>&1)" || true
echo "$VERIFY_OUT" | sed 's/^/  /'

AUTH_MODE="$(echo "$VERIFY_OUT" | sed -n 's/^auth_mode:[[:space:]]*//p' | head -1)"
CUTOVER_READY="$(echo "$VERIFY_OUT" | sed -n 's/^CUTOVER_READY=//p' | head -1)"
MINT_OK=no
if echo "$VERIFY_OUT" | grep -q 'Live token mint succeeded'; then
  MINT_OK=yes
fi

echo
echo "  parsed auth_mode: ${AUTH_MODE:-unknown}"
echo "  parsed CUTOVER_READY: ${CUTOVER_READY:-unknown}"
echo "  live token mint: ${MINT_OK}"

if [[ "$AUTH_MODE" != "github_app" ]]; then
  note_fail "auth_mode is not github_app (got ${AUTH_MODE:-unknown})"
fi
if [[ "$CUTOVER_READY" != "YES" ]]; then
  note_fail "CUTOVER_READY is not YES (got ${CUTOVER_READY:-unknown})"
fi
if [[ "$MINT_OK" != "yes" ]]; then
  note_fail "live token mint not confirmed"
fi
echo

echo "== 4. Recent backend logs (GitHub auth patterns) =="
inspect_backend_logs backend-aws
inspect_backend_logs backend-aws-canary
echo

echo "== Summary =="
if [[ ${#FAIL_REASONS[@]} -gt 0 ]]; then
  echo "Failures:"
  for reason in "${FAIL_REASONS[@]}"; do
    echo "  - $reason"
  done
else
  echo "Failures: none"
fi

if [[ "$EXCHANGE_WARN" == "yes" ]]; then
  echo "EXCHANGE_CREDENTIAL_WARNINGS=YES"
else
  echo "EXCHANGE_CREDENTIAL_WARNINGS=NO"
fi

if [[ "$OVERALL_PASS" == "yes" ]]; then
  echo "GITHUB_APP_CUTOVER_HEALTH=PASS"
  exit 0
else
  echo "GITHUB_APP_CUTOVER_HEALTH=FAIL"
  exit 1
fi
