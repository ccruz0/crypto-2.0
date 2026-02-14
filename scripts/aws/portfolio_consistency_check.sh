#!/usr/bin/env bash
# Capital drift detection: compare DB portfolio vs exchange summary.
# If drift > DRIFT_THRESHOLD_PCT (default 1%): FAIL. Output: PASS or FAIL only. No secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

DRIFT_THRESHOLD_PCT="${DRIFT_THRESHOLD_PCT:-1}"
export DRIFT_THRESHOLD_PCT

run_check() {
  if [[ "${DEBUG:-0}" == "1" ]]; then
    docker compose exec -T backend-aws python scripts/portfolio_consistency_check.py
  else
    docker compose exec -T backend-aws python scripts/portfolio_consistency_check.py 2>/dev/null
  fi
}
exit_code=0
run_check || exit_code=$?
if [[ $exit_code -ne 0 ]]; then
  echo "FAIL"
  exit 1
fi
echo "PASS"
exit 0
