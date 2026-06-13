#!/usr/bin/env bash
# Verify the expected frontend version entry exists in monorepo page.tsx.
# Used by CI and EC2 SSM deploy so workflow JSON avoids nested grep quotes.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EXPECTED_VERSION="${VERIFY_FRONTEND_VERSION:-0.46}"
PAGE="frontend/src/app/page.tsx"

if [[ ! -f "$PAGE" ]]; then
  echo "ERROR: $PAGE not found" >&2
  exit 1
fi

PATTERN="version: '${EXPECTED_VERSION}'"

if grep -Fq "$PATTERN" "$PAGE"; then
  echo "OK: found $PATTERN in $PAGE"
  exit 0
fi

echo "ERROR: expected frontend version entry not found: $PATTERN" >&2
echo "Current version lines:" >&2
grep -n "version:" "$PAGE" | head -5 >&2 || true
exit 1
