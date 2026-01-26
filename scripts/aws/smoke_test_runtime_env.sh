#!/usr/bin/env bash
# Smoke test: runtime.env exists and contains required KEY names only (no secrets printed).
# Usage: scripts/aws/smoke_test_runtime_env.sh [path-to-runtime.env]
# Default: <repo_root>/secrets/runtime.env
# Output: presence YES/NO, key names only. Never prints values.
set -euo pipefail
# Avoid xtrace; never log or echo secret values.
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUNTIME_ENV="${1:-$ROOT_DIR/secrets/runtime.env}"

if [[ ! -f "$RUNTIME_ENV" ]]; then
  echo "FAIL: presence=NO" >&2
  exit 1
fi

REQUIRED_KEYS=(
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  ADMIN_ACTIONS_KEY
  DIAGNOSTICS_API_KEY
  ENVIRONMENT
  RUN_TELEGRAM
)
missing=()
for k in "${REQUIRED_KEYS[@]}"; do
  if ! grep -qE "^${k}=" "$RUNTIME_ENV"; then
    missing+=("$k")
  fi
done

if (( ${#missing[@]} > 0 )); then
  echo "FAIL: presence=YES missing_keys=${missing[*]}" >&2
  exit 1
fi

echo "OK: presence=YES keys=${REQUIRED_KEYS[*]}"
exit 0
