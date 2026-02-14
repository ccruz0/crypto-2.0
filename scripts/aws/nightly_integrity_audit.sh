#!/usr/bin/env bash
# Nightly integrity audit entrypoint. Runs on EC2. PASS/FAIL only. On any failure: one Telegram alert, then exit 1.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

GIT_HASH="$(git -C "${REPO_ROOT}" rev-parse --short HEAD 2>/dev/null || echo "unknown")"
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

for i in "${!STEPS[@]}"; do
  step="${STEPS[$i]}"
  name="${STEP_NAMES[$i]}"
  if ! "${REPO_ROOT}/${step}" >/dev/null 2>&1; then
    ALERT_MSG="Nightly integrity FAIL: ${name} | git: ${GIT_HASH}"
    "${SCRIPT_DIR}/_notify_telegram_fail.sh" "${ALERT_MSG}" 2>/dev/null || true
    echo "FAIL"
    exit 1
  fi
done
echo "PASS"
exit 0
