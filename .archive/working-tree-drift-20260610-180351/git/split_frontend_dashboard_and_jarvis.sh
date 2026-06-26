#!/usr/bin/env bash
# Split the current frontend working tree into two commits:
#   Commit A — trading dashboard baseline
#   Commit B — Jarvis Phase 1 Advisor Control Center
#
# Hard rules: no deploy, no push, no backend/trading/ATP_TRADING_ONLY changes.
# Safe to re-run only when neither split commit exists yet.
#
# Usage:
#   ./scripts/git/split_frontend_dashboard_and_jarvis.sh
#   RUN_CONFIRM=1 ./scripts/git/split_frontend_dashboard_and_jarvis.sh
#   RUN_BUILD=1   ./scripts/git/split_frontend_dashboard_and_jarvis.sh

set -euo pipefail

COMMIT_A_MSG="chore(frontend): capture current trading dashboard baseline"
COMMIT_B_MSG="feat(jarvis): add advisor control center"
PAGE_BACKUP="/tmp/page.prod.tsx"
PAGE_BASELINE="/tmp/page.baseline.tsx"
MARKER_FILE="/tmp/jarvis-split-in-progress"

COMMIT_A_FILES=(
  frontend/src/app/context/PriceStreamContext.tsx
  frontend/src/app/components/ExchangeCredentialsModal.tsx
  frontend/.env.example
  frontend/.gitignore
  frontend/src/app/components/tabs/ExecutedOrdersTab.tsx
  frontend/src/app/components/tabs/OrdersTab.tsx
  frontend/src/app/components/tabs/WatchlistTab.tsx
  frontend/src/components/SystemHealth.tsx
  frontend/src/hooks/useOrders.ts
  frontend/src/lib/environment.ts
  frontend/src/hooks/usePriceWebSocket.ts
  frontend/src/lib/priceStreamWsUrl.ts
  frontend/src/components/MissingSecretsBanner.tsx
  frontend/src/components/RotateAdminKeyModal.tsx
  frontend/src/app/page.tsx
)

COMMIT_B_FILES=(
  frontend/src/app/components/tabs/JarvisTab.tsx
  frontend/src/app/components/tabs/AgentOpsTab.tsx
  frontend/tests/e2e/jarvis-tab.spec.ts
  frontend/src/app/jarvis/
  frontend/src/app/page.tsx
  frontend/src/app/monitoring/page.tsx
)

PARTIAL_STAGE_FILES=(
  frontend/src/app/api.ts
  frontend/src/lib/api.ts
)

JARVIS_HUNK_PATTERN='Jarvis|AgentOps|/jarvis/|/agent/ops/|agent/ops'

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

die() {
  echo "ERROR: $*" >&2
  exit 1
}

section() {
  echo ""
  echo "=================================================================="
  echo " $*"
  echo "=================================================================="
}

show_git_status() {
  section "git status --short"
  git status --short
}

show_staged_files() {
  section "Staged files (git diff --cached --name-status)"
  if git diff --cached --quiet 2>/dev/null; then
    echo "(nothing staged)"
  else
    git diff --cached --name-status
  fi
}

confirm_commit() {
  local msg="$1"
  if [[ "${RUN_CONFIRM:-}" == "1" ]]; then
    echo "RUN_CONFIRM=1 — auto-confirming commit: $msg"
    return 0
  fi
  echo ""
  echo "Ready to create commit:"
  echo "  $msg"
  read -r -p "Proceed with this commit? [y/N] " answer
  case "${answer:-}" in
    y|Y|yes|YES) ;;
    *) die "Commit aborted by user." ;;
  esac
}

print_rollback_help() {
  section "Rollback commands"
  cat <<EOF
If you need to undo this split before pushing:

  # Drop both split commits but keep working tree changes:
  git reset --soft HEAD~2

  # Drop commits and discard all local changes (destructive):
  git reset --hard ${ORIGINAL_BRANCH:-'<original-branch>'}

  # Restore production page.tsx from backup:
  cp ${PAGE_BACKUP} frontend/src/app/page.tsx

  # Remove in-progress marker (if present):
  rm -f ${MARKER_FILE}

Backup branch created at start (points to pre-split HEAD):
  ${BACKUP_BRANCH:-'(not created yet)'}

Current branch: ${ORIGINAL_BRANCH:-'(unknown)'}
EOF
}

cleanup_on_error() {
  local code=$?
  echo "" >&2
  echo "Script failed (exit ${code}). Working tree may be partially modified." >&2
  print_rollback_help >&2
  exit "${code}"
}

file_has_worktree_change() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    git ls-files --error-unmatch "$path" &>/dev/null && return 0
    return 1
  fi
  if git diff --quiet HEAD -- "$path" 2>/dev/null; then
    if git ls-files --others --exclude-standard -- "$path" | grep -q .; then
      return 0
    fi
    return 1
  fi
  return 0
}

worktree_has_split_changes() {
  local path
  for path in "${COMMIT_A_FILES[@]}" "${COMMIT_B_FILES[@]}" "${PARTIAL_STAGE_FILES[@]}"; do
    if file_has_worktree_change "$path"; then
      return 0
    fi
  done
  return 1
}

split_commits_already_exist() {
  git log --format=%s -30 | grep -Fxq "${COMMIT_A_MSG}" \
    || git log --format=%s -30 | grep -Fxq "${COMMIT_B_MSG}"
}

detect_jarvis_agent_ops_hunks() {
  local file="$1"
  local label="$2"
  local diff_output=""

  if [[ ! -f "$file" ]]; then
    return 1
  fi

  if ! git diff --quiet HEAD -- "$file" 2>/dev/null; then
    diff_output="$(git diff HEAD -- "$file" || true)"
  elif git ls-files --others --exclude-standard -- "$file" | grep -q .; then
    diff_output="$(git diff --no-index /dev/null "$file" 2>/dev/null || true)"
  else
    return 1
  fi

  if echo "${diff_output}" | grep -Eiq "${JARVIS_HUNK_PATTERN}"; then
    section "Jarvis / Agent Ops hunks detected in ${file} (${label})"
    echo "${diff_output}" | grep -Ein "${JARVIS_HUNK_PATTERN}" | head -40 || true
    return 0
  fi
  return 1
}

print_partial_stage_instructions() {
  local phase="$1"
  local found=0

  section "Manual partial staging required — ${phase}"

  if [[ "${phase}" == "Commit A (baseline)" ]]; then
    cat <<'EOF'
Do NOT fully stage api.ts files. Use interactive staging and EXCLUDE Jarvis / Agent Ops hunks.

For each file below, run:
  git add -p <file>

Commit A rules:
  - frontend/src/app/api.ts
      Stage hunks that do NOT add or modify Jarvis or Agent Ops symbols/endpoints.
      SKIP hunks containing: Jarvis, AgentOps, /jarvis/, /agent/ops/
  - frontend/src/lib/api.ts
      If hunks REMOVE legacy Jarvis code from lib/api.ts, stage those in Commit A.
      SKIP hunks that ADD new Jarvis or Agent Ops API surface.

After staging, verify with: git diff --cached --name-status
EOF
  else
    cat <<'EOF'
Stage the REMAINING Jarvis / Agent Ops hunks that were skipped in Commit A.

For each file below, run:
  git add -p <file>

Commit B rules:
  - frontend/src/app/api.ts
      Stage hunks for Jarvis Control Center and Agent Ops (Advisor read-only MVP).
  - frontend/src/lib/api.ts
      Stage any remaining Jarvis-related hunks not already committed in Commit A.

After staging, verify with: git diff --cached --name-status
EOF
  fi

  local file
  for file in "${PARTIAL_STAGE_FILES[@]}"; do
    if detect_jarvis_agent_ops_hunks "$file" "${phase}"; then
      found=1
      echo ""
      echo "  git add -p ${file}"
    elif [[ -f "$file" ]] && ! git diff --quiet HEAD -- "$file" 2>/dev/null; then
      found=1
      echo ""
      echo "  ${file} has changes (review with: git diff HEAD -- ${file})"
      echo "  git add -p ${file}"
    fi
  done

  if [[ "${found}" -eq 0 ]]; then
    echo "No Jarvis / Agent Ops hunks detected in api.ts files."
    echo "If those files still have unstaged baseline changes, stage them manually before continuing."
  fi
}

pause_for_partial_staging() {
  local phase="$1"
  print_partial_stage_instructions "${phase}"
  echo ""
  if [[ "${RUN_CONFIRM:-}" == "1" ]]; then
    echo "RUN_CONFIRM=1 — assuming partial staging for ${phase} is already done."
    show_staged_files
    return 0
  fi
  read -r -p "Press Enter after manual partial staging is complete (or Ctrl-C to abort)... " _
  show_staged_files
}

create_baseline_page() {
  cp "${PAGE_BACKUP}" "${PAGE_BASELINE}"

  sed -i "/import JarvisTab from/d" "${PAGE_BASELINE}"
  sed -i "s/ | 'jarvis'//" "${PAGE_BASELINE}"
  sed -i "/{ id: 'jarvis', label: 'Jarvis' },/d" "${PAGE_BASELINE}"
  sed -i "/{activeTab === 'jarvis' && <JarvisTab \/>}/d" "${PAGE_BASELINE}"

  cp "${PAGE_BASELINE}" frontend/src/app/page.tsx
  echo "Created baseline page.tsx (Jarvis tab references removed)."
}

stage_explicit_files() {
  local label="$1"
  shift
  local files=("$@")
  local path staged_any=0

  section "Staging ${label} files"
  for path in "${files[@]}"; do
    if file_has_worktree_change "$path"; then
      git add -- "${path}"
      staged_any=1
      echo "  staged: ${path}"
    else
      echo "  skip (no changes): ${path}"
    fi
  done

  if [[ "${staged_any}" -eq 0 ]]; then
    echo "WARNING: No ${label} files had detectable changes to stage."
  fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

trap cleanup_on_error ERR

section "Pre-flight checks"
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"
echo "Repository root: ${REPO_ROOT}"

ORIGINAL_BRANCH="$(git branch --show-current)"
echo "Current branch: ${ORIGINAL_BRANCH}"

if split_commits_already_exist; then
  print_rollback_help
  die "Split commits already exist on this branch. Re-run is unsafe."
fi

if [[ -f "${MARKER_FILE}" ]]; then
  print_rollback_help
  die "In-progress marker found (${MARKER_FILE}). A previous run may have been interrupted."
fi

show_git_status

if ! worktree_has_split_changes; then
  die "Working tree has no detectable changes in the split file sets. Nothing to split."
fi

BACKUP_BRANCH="backup/pre-jarvis-split-$(date +%Y%m%d-%H%M%S)"
section "Stage 1 — Create backup branch: ${BACKUP_BRANCH}"
show_git_status
git branch "${BACKUP_BRANCH}"
echo "Created backup branch (current HEAD preserved on ${ORIGINAL_BRANCH})."
show_git_status

touch "${MARKER_FILE}"

section "Stage 2 — Save production page.tsx backup"
show_git_status
cp frontend/src/app/page.tsx "${PAGE_BACKUP}"
echo "Saved: ${PAGE_BACKUP}"
show_git_status

# ---------------------------------------------------------------------------
# Commit A — trading dashboard baseline
# ---------------------------------------------------------------------------

section "Stage 3 — Prepare baseline page.tsx for Commit A"
show_git_status
create_baseline_page
show_git_status

section "Stage 4 — Stage Commit A explicit files"
show_git_status
stage_explicit_files "Commit A" "${COMMIT_A_FILES[@]}"
show_git_status
show_staged_files

section "Stage 5 — Commit A manual partial staging (api.ts)"
pause_for_partial_staging "Commit A (baseline)"
show_git_status
show_staged_files
confirm_commit "${COMMIT_A_MSG}"
git commit -m "${COMMIT_A_MSG}"
echo "Commit A created."
show_git_status

# ---------------------------------------------------------------------------
# Commit B — Jarvis Phase 1
# ---------------------------------------------------------------------------

section "Stage 6 — Restore production page.tsx for Commit B"
show_git_status
if [[ ! -f "${PAGE_BACKUP}" ]]; then
  die "Page backup missing: ${PAGE_BACKUP}. Cannot restore Jarvis tab for Commit B."
fi
cp "${PAGE_BACKUP}" frontend/src/app/page.tsx
echo "Restored: frontend/src/app/page.tsx from ${PAGE_BACKUP}"
show_git_status

section "Stage 7 — Stage Commit B explicit files"
show_git_status
stage_explicit_files "Commit B" "${COMMIT_B_FILES[@]}"
show_git_status
show_staged_files

section "Stage 8 — Commit B manual partial staging (api.ts)"
pause_for_partial_staging "Commit B (Jarvis / Agent Ops)"
show_git_status
show_staged_files
confirm_commit "${COMMIT_B_MSG}"
git commit -m "${COMMIT_B_MSG}"
echo "Commit B created."
show_git_status

rm -f "${MARKER_FILE}" "${PAGE_BASELINE}"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

section "Recent commits"
git log --oneline -2

show_git_status

print_rollback_help

if [[ "${RUN_BUILD:-}" == "1" ]]; then
  section "RUN_BUILD=1 — building frontend"
  (cd frontend && npm run build)
else
  echo ""
  echo "Skipping build (set RUN_BUILD=1 to run: cd frontend && npm run build)"
fi

section "Done"
echo "Split complete. No deploy or push was performed."
echo "Backup branch: ${BACKUP_BRANCH}"
