#!/usr/bin/env bash
# Production port check: backend (8002) and frontend (3000) must be 127.0.0.1-bound in compose.
# Output: PASS or FAIL only. No secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="$ROOT/docker-compose.yml"

if [[ ! -f "$COMPOSE" ]]; then
  echo "FAIL"
  exit 1
fi
cd "$ROOT"
FAIL=()
PORT_LINES="$(grep -E '^\s+-\s+"[^"]*:[0-9]+:[0-9]+"' "$COMPOSE" 2>/dev/null || true)"
if echo "$PORT_LINES" | grep -qE '"0\.0\.0\.0:8002'; then
  FAIL+=(8002)
fi
if echo "$PORT_LINES" | grep -qE '"0\.0\.0\.0:3000'; then
  FAIL+=(3000)
fi
if ! grep -qF '127.0.0.1:8002:8002' "$COMPOSE"; then
  FAIL+=(8002)
fi
if ! grep -qF '127.0.0.1:3000:3000' "$COMPOSE"; then
  FAIL+=(3000)
fi
UNIQ=()
for p in "${FAIL[@]+"${FAIL[@]}"}"; do
  if [[ " ${UNIQ[*]:-} " != *" $p "* ]]; then UNIQ+=("$p"); fi
done
if (( ${#UNIQ[@]} > 0 )); then
  echo "FAIL"
  exit 1
fi
echo "PASS"
exit 0
