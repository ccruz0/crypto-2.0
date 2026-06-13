#!/usr/bin/env bash
# Hard guard: production deploy must use monorepo ./frontend only.
# Never clone, pull, rsync, copy, or overlay ccruz0/frontend or OpenClaw UI paths.
#
# Usage:
#   bash scripts/verify_no_external_frontend_deploy.sh --ci [extra-file]   # optional extra scan target (tests)
#   bash scripts/verify_no_external_frontend_deploy.sh --runtime    # EC2 before Docker build

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

MODE="${1:-}"
EXTRA_SCAN="${2:-}"
failures=0

fail() {
  echo "ERROR: $*" >&2
  failures=$((failures + 1))
}

DEPLOY_ARTIFACTS=(
  ".github/workflows/deploy_session_manager.yml"
)
if [[ -n "$EXTRA_SCAN" ]]; then
  DEPLOY_ARTIFACTS+=("$EXTRA_SCAN")
fi

# Scripts may mention forbidden paths when checking they must NOT exist.
SCAN_ALLOWLIST=(
  "scripts/verify_clean_worktree.sh"
  "scripts/verify_no_external_frontend_deploy.sh"
  "scripts/test_verify_no_external_frontend_deploy.sh"
)

is_allowlisted() {
  local rel="$1"
  local allowed
  for allowed in "${SCAN_ALLOWLIST[@]}"; do
    if [[ "$rel" == "$allowed" ]]; then
      return 0
    fi
  done
  return 1
}

FORBIDDEN_LITERALS=(
  "ccruz0/frontend"
  "github.com/ccruz0/frontend"
  "frontend/src/app/openclaw"
  "frontend/src/app/components/tabs/OpenClawTab.tsx"
)

FORBIDDEN_REGEXES=(
  'git[[:space:]]+clone.*frontend\.git'
  'git[[:space:]]+-C[[:space:]]+frontend[[:space:]]+pull'
  'rm[[:space:]]+-rf[[:space:]]+frontend'
)

scan_deploy_artifact() {
  local file="$1"
  if [[ ! -f "$file" ]]; then
    fail "deploy artifact missing: $file"
    return
  fi
  if is_allowlisted "$file"; then
    return
  fi

  local literal pattern
  for literal in "${FORBIDDEN_LITERALS[@]}"; do
    if grep -qF "$literal" "$file"; then
      fail "forbidden deploy reference in $file: $literal"
    fi
  done
  for pattern in "${FORBIDDEN_REGEXES[@]}"; do
    if grep -qE "$pattern" "$file"; then
      fail "forbidden deploy command in $file (pattern: $pattern)"
    fi
  done
}

verify_runtime_frontend() {
  if [[ ! -d frontend ]]; then
    fail "monorepo frontend/ directory missing at $REPO_ROOT/frontend"
    return
  fi
  if [[ -d frontend/.git ]]; then
    fail "frontend/ is a nested git repo — must use monorepo ./frontend at same commit"
  fi
  if [[ ! -f frontend/package.json ]]; then
    fail "frontend/package.json missing — not a valid monorepo frontend tree"
  fi
  if [[ ! -f frontend/Dockerfile ]]; then
    fail "frontend/Dockerfile missing — Docker build expects monorepo frontend/"
  fi

  local forbidden
  for forbidden in \
    "frontend/src/app/openclaw" \
    "frontend/src/app/components/tabs/OpenClawTab.tsx"; do
    if [[ -e "$forbidden" ]]; then
      fail "forbidden OpenClaw frontend path on disk: $forbidden"
    fi
  done
}

case "$MODE" in
  --ci)
    echo "==> verify_no_external_frontend_deploy (--ci)"
    for artifact in "${DEPLOY_ARTIFACTS[@]}"; do
      scan_deploy_artifact "$artifact"
    done
    ;;
  --runtime)
    echo "==> verify_no_external_frontend_deploy (--runtime)"
    verify_runtime_frontend
    ;;
  *)
    echo "Usage: $0 --ci | --runtime" >&2
    exit 2
    ;;
esac

if [[ "$failures" -gt 0 ]]; then
  echo "verify_no_external_frontend_deploy: FAILED ($failures issue(s))" >&2
  exit 1
fi

echo "verify_no_external_frontend_deploy: OK"
