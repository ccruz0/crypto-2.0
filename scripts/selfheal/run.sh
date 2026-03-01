#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERIFY="$REPO_ROOT/scripts/selfheal/verify.sh"
HEAL="$REPO_ROOT/scripts/selfheal/heal.sh"

echo "Self-heal run: $(date -Is)"

if "$VERIFY" >/tmp/atp-verify.json 2>/tmp/atp-verify.err; then
  echo "PASS"
  exit 0
fi

reason="$(tail -n 1 /tmp/atp-verify.err 2>/dev/null || true)"
echo "Verify failed: ${reason:-unknown}"

"$HEAL" || true

if "$VERIFY" >/tmp/atp-verify.json 2>/tmp/atp-verify.err; then
  echo "HEALED"
  exit 0
fi

echo "STILL_FAIL"
exit 1
