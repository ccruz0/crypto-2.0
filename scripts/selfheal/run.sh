#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERIFY="${ATP_SELFHEAL_VERIFY:-$REPO_ROOT/scripts/selfheal/verify.sh}"
HEAL="${ATP_SELFHEAL_HEAL:-$REPO_ROOT/scripts/selfheal/heal.sh}"
DEPLOY_MARKER="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"
DEPLOY_MARKER_TTL="${ATP_DEPLOY_MARKER_TTL_SECS:-1800}"
COOLDOWN_FILE="${ATP_SELFHEAL_COOLDOWN_FILE:-/tmp/atp-selfheal-last-action}"
COOLDOWN_SECS="${ATP_SELFHEAL_COOLDOWN_SECS:-900}"

# Returns 0 if a deploy is genuinely in progress (fresh marker), 1 otherwise.
# A marker older than the TTL is treated as stale (the deploy process likely
# died without cleaning up) and is removed so self-heal is not blocked forever.
deploy_marker_active() {
  [ -f "$DEPLOY_MARKER" ] || return 1
  local now epoch age
  now="$(date +%s)"
  epoch="$(sed -n 's/.*epoch=\([0-9]\{1,\}\).*/\1/p' "$DEPLOY_MARKER" 2>/dev/null | head -1)"
  if [ -z "$epoch" ]; then
    epoch="$(stat -c %Y "$DEPLOY_MARKER" 2>/dev/null || echo 0)"
  fi
  age=$((now - epoch))
  if [ "$age" -lt "$DEPLOY_MARKER_TTL" ]; then
    return 0
  fi
  echo "STALE_DEPLOY_MARKER: age=${age}s >= ttl=${DEPLOY_MARKER_TTL}s; removing and proceeding"
  rm -f "$DEPLOY_MARKER" 2>/dev/null || true
  return 1
}

echo "Self-heal run: $(date -Is)"

if deploy_marker_active; then
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
