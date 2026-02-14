#!/usr/bin/env bash
# Portfolio consistency: PASS only when drift <= threshold and data available.
# FAIL on missing data (unless ALLOW_EMPTY_PORTFOLIO=1), drift > threshold, or exception.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_CMD=(docker compose --profile aws)
out="$("${COMPOSE_CMD[@]}" exec -T backend-aws python3 /app/scripts/portfolio_consistency_check.py 2>&1)" || true
if [[ "$out" == *"PASS"* ]]; then
  echo "PASS"
  exit 0
fi
[[ -n "${DEBUG:-}" ]] && echo "$out"
echo "FAIL"
exit 1
