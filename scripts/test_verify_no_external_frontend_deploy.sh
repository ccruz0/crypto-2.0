#!/usr/bin/env bash
# Regression test: production deploy workflow must not reference external frontend repo.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DEPLOY_ARTIFACTS=(
  ".github/workflows/deploy_session_manager.yml"
  ".github/workflows/deploy.yml"
  ".github/workflows/dashboard-data-integrity.yml"
  "scripts/aws/deploy_all_manual_commands.sh"
)
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

for artifact in "${DEPLOY_ARTIFACTS[@]}"; do
  echo "-- $artifact must not mention external frontend repo"
  if grep -qE 'ccruz0/frontend|github\.com/ccruz0/frontend' "$artifact"; then
    echo "FAIL: $artifact still references ccruz0/frontend" >&2
    exit 1
  fi

  echo "-- $artifact must not clone external frontend"
  if grep -qE 'git clone.*frontend\.git' "$artifact"; then
    echo "FAIL: $artifact still clones external frontend" >&2
    exit 1
  fi
done

echo "-- deploy workflows must call verify_no_external_frontend_deploy.sh"
for workflow in \
  ".github/workflows/deploy_session_manager.yml" \
  ".github/workflows/deploy.yml" \
  ".github/workflows/dashboard-data-integrity.yml"; do
  grep -q 'verify_no_external_frontend_deploy.sh' "$workflow" || {
    echo "FAIL: $workflow must invoke verify_no_external_frontend_deploy.sh" >&2
    exit 1
  }
done

echo "-- deploy_session_manager SSM git pull must run as ubuntu"
grep -q 'sudo -u ubuntu git -C /home/ubuntu/crypto-2.0 fetch origin main' .github/workflows/deploy_session_manager.yml || {
  echo "FAIL: deploy_session_manager.yml must fetch as ubuntu via sudo -u ubuntu git -C" >&2
  exit 1
}
grep -q 'sudo -u ubuntu git -C /home/ubuntu/crypto-2.0 pull --ff-only origin main' .github/workflows/deploy_session_manager.yml || {
  echo "FAIL: deploy_session_manager.yml must pull as ubuntu via sudo -u ubuntu git -C" >&2
  exit 1
}

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cp ".github/workflows/deploy_session_manager.yml" "$TMP"
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
