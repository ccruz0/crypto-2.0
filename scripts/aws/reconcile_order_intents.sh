#!/usr/bin/env bash
# Reconcile stale order intents (no exchange order) and mark as FAILED.
# Uses docker compose exec backend-aws. Output: PASS or FAIL only. No secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

RECONCILE_GRACE_MINUTES="${RECONCILE_GRACE_MINUTES:-5}"
export RECONCILE_GRACE_MINUTES

run_reconcile() {
  if [[ "${DEBUG:-0}" == "1" ]]; then
    docker compose exec -T backend-aws python scripts/reconcile_order_intents.py
  else
    docker compose exec -T backend-aws python scripts/reconcile_order_intents.py 2>/dev/null
  fi
}
if ! run_reconcile; then
  echo "FAIL"
  exit 1
fi
echo "PASS"
exit 0
