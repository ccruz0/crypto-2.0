#!/usr/bin/env bash
# Fail before Docker frontend builds if the working tree can bake drift into images.
#
# Docker build context is ./frontend on disk, not git HEAD. Untracked routes and
# local edits are copied into frontend-aws unless this check runs first.
#
# Usage: bash scripts/verify_clean_worktree.sh [--frontend-only]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FRONTEND_ONLY=0
if [[ "${1:-}" == "--frontend-only" ]]; then
  FRONTEND_ONLY=1
fi

failures=0

fail() {
  echo "ERROR: $*" >&2
  failures=$((failures + 1))
}

echo "==> verify_clean_worktree (repo=$REPO_ROOT)"

# --- tracked frontend modifications/deletions ---
modified_frontend="$(git status --porcelain -- frontend/ | grep -v '^??' || true)"
if [[ -n "$modified_frontend" ]]; then
  echo "Modified/deleted tracked frontend files:" >&2
  echo "$modified_frontend" >&2
  fail "frontend/ has tracked changes vs HEAD"
fi

# --- untracked frontend files (routes, tabs, helpers) ---
untracked_frontend="$(git status --porcelain --untracked-files=all -- frontend/ | grep '^??' || true)"
if [[ -n "$untracked_frontend" ]]; then
  echo "Untracked frontend files:" >&2
  echo "$untracked_frontend" >&2
  fail "frontend/ has untracked files that would enter Docker build context"
fi

# --- forbidden OpenClaw frontend surface ---
for forbidden in \
  "frontend/src/app/openclaw" \
  "frontend/src/app/components/tabs/OpenClawTab.tsx" \
  "frontend/src/app/components/tabs/AgentOpsTab.tsx"; do
  if [[ -e "$forbidden" ]]; then
    fail "forbidden OpenClaw frontend path exists: $forbidden"
  fi
done

page_tsx="frontend/src/app/page.tsx"
if [[ -f "$page_tsx" ]]; then
  if grep -qE "id:\s*['\"]openclaw['\"]" "$page_tsx" && grep -q "OpenClaw" "$page_tsx"; then
    fail "OpenClaw dashboard tab entry detected in $page_tsx"
  fi
fi

if [[ "$FRONTEND_ONLY" == "1" ]]; then
  if [[ "$failures" -gt 0 ]]; then
    echo "verify_clean_worktree: FAILED ($failures issue(s))" >&2
    exit 1
  fi
  echo "verify_clean_worktree: OK (frontend checks)"
  exit 0
fi

# --- OpenClaw artifacts outside archive/docs/lab tooling ---
OPENCLAW_ALLOW_PREFIXES=(
  "docs/"
  ".archive/"
  "archive/"
  "scripts/openclaw/"
  "openclaw/"
  ".git/"
  "node_modules/"
  ".next/"
  "frontend/node_modules/"
  "frontend/.next/"
)

is_allowed_openclaw_path() {
  local rel="$1"
  local prefix
  for prefix in "${OPENCLAW_ALLOW_PREFIXES[@]}"; do
    if [[ "$rel" == "$prefix"* ]]; then
      return 0
    fi
  done
  return 1
}

while IFS= read -r -d '' path; do
  rel="${path#./}"
  if is_allowed_openclaw_path "$rel"; then
    continue
  fi
  case "$rel" in
    scripts/automation/openclaw_guard.py|scripts/check_openclaw_health.sh|docker-compose.openclaw.yml)
      continue
      ;;
  esac
  if [[ "$rel" == frontend/* ]]; then
    fail "OpenClaw-related file in frontend build tree: $rel"
  fi
done < <(find . -iregex '.*openclaw.*' -not -path './.git/*' -print0 2>/dev/null || true)

if [[ "$failures" -gt 0 ]]; then
  echo "verify_clean_worktree: FAILED ($failures issue(s))" >&2
  exit 1
fi

echo "verify_clean_worktree: OK"
