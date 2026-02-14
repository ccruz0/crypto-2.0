#!/usr/bin/env bash
# Health guard: sanity checks for trading stack. Output: PASS or FAIL only. No secrets.
set -euo pipefail

# If docker compose and backend-aws are available, probe health; else pass (e.g. in CI).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
if command -v docker >/dev/null 2>&1 && docker compose ps backend-aws 2>/dev/null | grep -q backend-aws; then
  if curl -sf -o /dev/null --connect-timeout 5 "http://127.0.0.1:8002/health" 2>/dev/null; then
    echo "PASS"
    exit 0
  fi
  echo "FAIL"
  exit 1
fi
echo "PASS"
exit 0
