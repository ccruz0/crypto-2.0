#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERIFY="$REPO_ROOT/scripts/selfheal/verify.sh"
HEAL="$REPO_ROOT/scripts/selfheal/heal.sh"
DEPLOY_MARKER="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"
COOLDOWN_FILE="${ATP_SELFHEAL_COOLDOWN_FILE:-/tmp/atp-selfheal-last-action}"
COOLDOWN_SECS="${ATP_SELFHEAL_COOLDOWN_SECS:-900}"

echo "Self-heal run: $(date -Is)"

if [ -f "$DEPLOY_MARKER" ]; then
  echo "DEPLOY_IN_PROGRESS: skipping self-heal"
  exit 0
fi

if [ -f "$COOLDOWN_FILE" ]; then
  last="$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  elapsed=$((now - last))
  if [ "$elapsed" -lt "$COOLDOWN_SECS" ]; then
    echo "COOLDOWN: last recovery attempt ${elapsed}s ago (minimum ${COOLDOWN_SECS}s); skipping"
    exit 0
  fi
fi

if "$VERIFY" >/tmp/atp-verify.json 2>/tmp/atp-verify.err; then
  echo "PASS"
  exit 0
fi

# verify.sh writes FAIL:* lines to stdout; stderr is often empty (root cause of "unknown").
reason="$(grep -E '^FAIL:' /tmp/atp-verify.json 2>/dev/null | tail -n 1 || true)"
if [ -z "$reason" ]; then
  reason="$(tail -n 1 /tmp/atp-verify.err 2>/dev/null || true)"
fi

if [ -z "$reason" ] || [[ ! "$reason" =~ ^FAIL: ]]; then
  echo "VERIFY_DEGRADED: unknown or unparseable verify failure; skipping recovery"
  echo "verify stdout (last 30 lines):"
  tail -n 30 /tmp/atp-verify.json 2>/dev/null || true
  if [ -s /tmp/atp-verify.err ]; then
    echo "verify stderr:"
    cat /tmp/atp-verify.err
  fi
  exit 1
fi

echo "Verify failed: $reason"

if [ "${ATP_SELFHEAL_DRY_RUN:-}" = "1" ] || [ "${1:-}" = "--dry-run" ]; then
  "$HEAL" --dry-run "$reason"
  exit 0
fi

"$HEAL" "$reason" || true

if "$VERIFY" >/tmp/atp-verify.json 2>/tmp/atp-verify.err; then
  echo "HEALED"
  exit 0
fi

echo "STILL_FAIL"
exit 1
