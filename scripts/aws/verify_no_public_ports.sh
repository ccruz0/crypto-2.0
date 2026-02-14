#!/usr/bin/env bash
# Enforce localhost-only for AWS profile: backend-aws (8002) and frontend-aws (3000).
# FAIL if docker-compose.yml contains "0.0.0.0:8002" or "0.0.0.0:3000".
# PASS only if it contains both "127.0.0.1:8002:8002" and "127.0.0.1:3000:3000".
# Output: PASS or FAIL only. No secrets.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE="$ROOT/docker-compose.yml"

if [[ ! -f "$COMPOSE" ]]; then
  echo "FAIL"
  exit 1
fi

# Fail if public bindings exist (0.0.0.0 exposure)
if grep -qE '"0\.0\.0\.0:8002"|"0\.0\.0\.0:3000"' "$COMPOSE"; then
  echo "FAIL"
  exit 1
fi

# Pass only if AWS profile has localhost-only bindings
if grep -qF '127.0.0.1:8002:8002' "$COMPOSE" && grep -qF '127.0.0.1:3000:3000' "$COMPOSE"; then
  echo "PASS"
  exit 0
fi

echo "FAIL"
exit 1
