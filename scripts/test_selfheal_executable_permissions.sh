#!/usr/bin/env bash
# Fail if core self-heal scripts are not tracked as executable (git mode 100755).
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

REQUIRED=(
  scripts/selfheal/run.sh
  scripts/selfheal/heal.sh
  scripts/selfheal/verify.sh
)

fail=0
for path in "${REQUIRED[@]}"; do
  mode="$(git ls-files -s "$path" | awk '{print $1}')"
  if [ -z "$mode" ]; then
    echo "FAIL: $path is not tracked by git"
    fail=1
    continue
  fi
  if [ "$mode" != "100755" ]; then
    echo "FAIL: $path has git mode $mode (expected 100755)"
    fail=1
    continue
  fi
  echo "PASS: $path (100755)"
done

if [ "$fail" -ne 0 ]; then
  echo "Self-heal executable permission guard failed."
  echo "Fix with: git update-index --chmod=+x scripts/selfheal/run.sh scripts/selfheal/heal.sh scripts/selfheal/verify.sh"
  exit 1
fi

echo "Self-heal executable permission guard passed."
