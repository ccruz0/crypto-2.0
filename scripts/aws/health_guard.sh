#!/usr/bin/env bash
# Health guard: sanity checks for trading stack. Output: PASS or FAIL only. No secrets.
set -euo pipefail

# If docker compose and backend-aws are available, probe health; else pass (e.g. in CI).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT"
if command -v docker >/dev/null 2>&1 && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q backend-aws; then
  # Retry curl a few times (backend can be "Up" but not yet responding right after ensure_stack_up)
  for _ in 1 2 3 4 5; do
    if curl -sf -o /dev/null --connect-timeout 5 --max-time 5 "http://127.0.0.1:8002/health" 2>/dev/null; then
      echo "PASS"
      exit 0
    fi
    sleep 2
  done
  echo "FAIL (curl /health failed after 5 attempts)" >&2
  curl -s -o /dev/null -w "last_curl_http=%{http_code}\n" --connect-timeout 2 --max-time 2 "http://127.0.0.1:8002/health" 2>&1 || true
  echo "FAIL"
  exit 1
fi
echo "PASS"
exit 0
