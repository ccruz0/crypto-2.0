#!/usr/bin/env bash
# Order intent reconciliation: PASS only when reconciled and zero stale intents.
# FAIL on DB unreachable after retries or when stale intents remain.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

COMPOSE_CMD=(docker compose --profile aws)
MAX_RETRIES=2
SLEEP_BETWEEN=15

for attempt in $(seq 1 "$MAX_RETRIES"); do
  out="$("${COMPOSE_CMD[@]}" exec -T backend-aws python3 /app/scripts/reconcile_order_intents.py 2>&1)" || true
  if [[ "$out" == *"PASS"* ]]; then
    echo "PASS"
    exit 0
  fi
  if [[ "$out" == *"FAIL"* ]]; then
    [[ -n "${DEBUG:-}" ]] && echo "$out"
    echo "FAIL"
    exit 1
  fi
  if [[ $attempt -lt $MAX_RETRIES ]]; then
    [[ -n "${DEBUG:-}" ]] && echo "Attempt $attempt: retrying in ${SLEEP_BETWEEN}s"
    sleep "$SLEEP_BETWEEN"
  fi
done
echo "FAIL"
exit 1
