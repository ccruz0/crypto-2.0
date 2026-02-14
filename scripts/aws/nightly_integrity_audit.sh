#!/usr/bin/env bash
# Nightly integrity audit entrypoint. Runs on EC2. PASS/FAIL only. On any failure: one Telegram alert, then exit 1.
set -euo pipefail
# Safe PS4 for tracing (bash -x): FUNCNAME[0] can be unset at top-level; :-MAIN avoids set -u break
PS4='+ ${BASH_SOURCE}:${LINENO}:${FUNCNAME[0]:-MAIN}: '

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

GIT_HASH="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"

# Start stack if needed so audit never runs against "nothing listening on 8002"
ensure_stack_up() {
  cd "$REPO_ROOT"

  # Start required services (idempotent)
  docker compose --profile aws up -d db backend-aws >/dev/null 2>&1 || return 1

  # Wait up to 120s for API
  local tries=24
  local sleep_s=5
  local i=1

  while [ "$i" -le "$tries" ]; do
    if curl -fsS --max-time 2 http://127.0.0.1:8002/api/health/system >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_s"
    i=$((i+1))
  done

  return 1
}

run_with_retries() {
  local cmd="$1"
  local name="$2"
  local retries="${3:-3}"
  local delay="${4:-5}"
  local i=1
  while true; do
    if "${cmd}" >/dev/null 2>&1; then
      return 0
    fi
    if [[ $i -ge $retries ]]; then
      return 1
    fi
    sleep "$delay"
    i=$((i + 1))
  done
}

# Wait for backend to answer (simple /health) before burning health_guard retries
wait_for_backend_ready() {
  local tries="${1:-18}"   # 18 x 5s = 90s
  local sleep_s="${2:-5}"
  local i=1
  while [[ "$i" -le "$tries" ]]; do
    if curl -fsS --max-time 5 http://127.0.0.1:8002/health >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_s"
    i=$((i + 1))
  done
  # Diagnostic: one verbose curl so logs show why (connection refused, timeout, etc.)
  echo "Backend not ready after ${tries} tries; last curl attempt:" >&2
  curl -v --max-time 5 http://127.0.0.1:8002/health 2>&1 || true
  return 1
}

STEPS=(
  "scripts/aws/verify_no_public_ports.sh"
  "scripts/aws/health_guard.sh"
  "scripts/aws/stability_check.sh"
  "scripts/aws/reconcile_order_intents.sh"
  "scripts/aws/portfolio_consistency_check.sh"
)
STEP_NAMES=(
  "verify_no_public_ports"
  "health_guard"
  "stability_check"
  "reconcile_order_intents"
  "portfolio_consistency_check"
)

if ! ensure_stack_up; then
  echo "FAIL"
  exit 1
fi

for i in "${!STEPS[@]}"; do
  step="${STEPS[$i]}"
  name="${STEP_NAMES[$i]}"
  if [[ "$name" == "health_guard" ]]; then
    if ! wait_for_backend_ready 18 5; then
      echo "Audit FAIL: backend not ready within 90s (health_guard not run)" >&2
      exit 1
    fi
    if ! run_with_retries "${REPO_ROOT}/${step}" "health_guard" 5 10; then
      ALERT_MSG="Nightly integrity FAIL: ${name} | git: ${GIT_HASH}"
      "${SCRIPT_DIR}/_notify_telegram_fail.sh" "${ALERT_MSG}" 2>/dev/null || true
      echo "FAIL"
      exit 1
    fi
  elif ! "${REPO_ROOT}/${step}" >/dev/null 2>&1; then
    ALERT_MSG="Nightly integrity FAIL: ${name} | git: ${GIT_HASH}"
    "${SCRIPT_DIR}/_notify_telegram_fail.sh" "${ALERT_MSG}" 2>/dev/null || true
    echo "FAIL"
    exit 1
  fi
done
echo "PASS"
exit 0
