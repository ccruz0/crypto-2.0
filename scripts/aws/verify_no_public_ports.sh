#!/usr/bin/env bash
# Static check: backend (8002) and frontend (3000) must be 127.0.0.1-bound in docker-compose.yml.
# Fail if "0.0.0.0:8002", "0.0.0.0:3000", or bare "8002:8002" / "3000:3000" appear.
# Pass only if both "127.0.0.1:8002:8002" and "127.0.0.1:3000:3000" exist.
# Output: PASS or FAIL only. No secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="$ROOT/docker-compose.yml"

if [[ ! -f "$COMPOSE" ]]; then
  echo "FAIL"
  exit 1
fi

# Fail if public bindings exist
if grep -qE '"0\.0\.0\.0:8002"|"0\.0\.0\.0:3000"' "$COMPOSE"; then
  echo "FAIL"
  exit 1
fi
# Fail if bare "8002:8002" or "3000:3000" appears (line without 127.0.0.1)
if grep '"8002:8002"' "$COMPOSE" | grep -v -q '127.0.0.1'; then
  echo "FAIL"
  exit 1
fi
if grep '"3000:3000"' "$COMPOSE" | grep -v -q '127.0.0.1'; then
  echo "FAIL"
  exit 1
fi

# Pass only if both required bindings exist
if grep -qF '127.0.0.1:8002:8002' "$COMPOSE" && grep -qF '127.0.0.1:3000:3000' "$COMPOSE"; then
  echo "PASS"
  exit 0
fi

echo "FAIL"
exit 1
