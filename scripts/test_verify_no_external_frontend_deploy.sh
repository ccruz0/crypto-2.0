#!/usr/bin/env bash
# Regression test: production deploy workflow must not reference external frontend repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

WORKFLOW=".github/workflows/deploy_session_manager.yml"
GUARD="scripts/verify_no_external_frontend_deploy.sh"

echo "==> test_verify_no_external_frontend_deploy"

if [[ ! -x "$GUARD" ]]; then
  chmod +x "$GUARD"
fi

echo "-- guard --ci must pass on current tree"
bash "$GUARD" --ci

echo "-- guard --runtime (monorepo frontend must not be nested git repo)"
if [[ -d frontend/.git ]]; then
  echo "   local frontend/.git detected — guard must reject nested repo"
  if bash "$GUARD" --runtime 2>/dev/null; then
    echo "FAIL: guard --runtime should reject nested frontend/.git" >&2
    exit 1
  fi
else
  bash "$GUARD" --runtime
fi

echo "-- workflow must not mention external frontend repo"
if grep -qE 'ccruz0/frontend|github\.com/ccruz0/frontend' "$WORKFLOW"; then
  echo "FAIL: $WORKFLOW still references ccruz0/frontend" >&2
  exit 1
fi

echo "-- workflow must not clone or remove monorepo frontend/"
if grep -qE 'git clone.*frontend\.git|rm -rf frontend' "$WORKFLOW"; then
  echo "FAIL: $WORKFLOW still clones or deletes frontend/" >&2
  exit 1
fi

echo "-- workflow must call verify_no_external_frontend_deploy.sh"
grep -q 'verify_no_external_frontend_deploy.sh' "$WORKFLOW" || {
  echo "FAIL: $WORKFLOW must invoke verify_no_external_frontend_deploy.sh" >&2
  exit 1
}

echo "-- guard rejects synthetic forbidden reference"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cp "$WORKFLOW" "$TMP"
printf '\n# bad: ccruz0/frontend\n' >> "$TMP"
if ! grep -qF 'ccruz0/frontend' "$TMP"; then
  echo "FAIL: synthetic test setup broken" >&2
  exit 1
fi
if bash "$GUARD" --ci "$TMP" 2>/dev/null; then
  echo "FAIL: guard --ci should fail when ccruz0/frontend is present" >&2
  exit 1
fi

echo "test_verify_no_external_frontend_deploy: OK"
