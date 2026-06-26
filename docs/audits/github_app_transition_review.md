# GitHub App Transition — Uncommitted Changes Review

**Date:** 2026-06-09  
**Branch:** `feat/github-app-transition-mode` (from `cb175c2`)  
**Base:** Path canonicalization commit only — PR #33 scope  
**Purpose:** Apply after PR #33 merges; enables PAT transition until GitHub App exists

---

## Files under review (4)

| File | Lines changed | Category |
|------|---------------|----------|
| `scripts/aws/render_runtime_env.sh` | +31 / −4 | Auth render logic |
| `backend/docs/GITHUB_APP_AUTH.md` | +8 | Documentation |
| `scripts/verify_deploy_secrets.sh` | +6 | Diagnostics output |
| `secrets/runtime.env.example` | +10 / −1 | Example comments |

**Total:** 4 files, ~51 insertions, ~5 deletions (uncommitted)

---

## Per-file analysis

### 1. `scripts/aws/render_runtime_env.sh`

| Check | Result |
|-------|--------|
| Unrelated changes | **None** |
| Path migration | **None** — SSM paths unchanged |
| Trading | **None** |
| OpenClaw | **None** |
| Auth logic | **Yes** — intentional |

**Change:** After all runtime.env merges, detect GitHub auth mode from rendered file:
- All three `GITHUB_APP_*` keys present → `github_app`, remove `ALLOW_LEGACY_GITHUB_PAT`
- `GITHUB_TOKEN` present, App incomplete → `legacy_transition`, set `ALLOW_LEGACY_GITHUB_PAT=true`
- Neither → `none`, remove `ALLOW_LEGACY_GITHUB_PAT`

**Verdict:** Safe for transition commit.

---

### 2. `backend/docs/GITHUB_APP_AUTH.md`

| Check | Result |
|-------|--------|
| Unrelated changes | **None** |
| Path migration | **None** |
| Trading / OpenClaw | **None** |

**Change:** New "Transition period (deploy after PR #32)" section documenting auto-`ALLOW_LEGACY` behavior and post-cutover PAT revocation steps.

**Verdict:** Safe — docs only.

---

### 3. `scripts/verify_deploy_secrets.sh`

| Check | Result |
|-------|--------|
| Unrelated changes | **None** |
| Path migration | **None** — path comment already in `cb175c2`; this diff adds auth only |
| Trading / OpenClaw | **None** |

**Change:** Prints `auth_mode: github_app | legacy_transition | none` based on container env.

**Verdict:** Safe — read-only diagnostics.

---

### 4. `secrets/runtime.env.example`

| Check | Result |
|-------|--------|
| Unrelated changes | **None** |
| Path migration | **None** — `ATP_PROJECT_PATH=/home/ubuntu/crypto-2.0` already in base `cb175c2`; not re-touched |
| Trading / OpenClaw | **None** |
| Secret values | **None added** |

**Change:** Replaces one-line GitHub comment with documented App keys, PAT fallback, and `ALLOW_LEGACY_GITHUB_PAT` example (all commented).

**Verdict:** Safe — example/documentation only.

---

## Constraint checklist

| Constraint | Violations |
|------------|------------|
| No unrelated changes | **None** |
| No path migration in this diff | **Pass** |
| No trading logic | **Pass** |
| No OpenClaw changes | **Pass** |
| No PAT removal | **Pass** — enables PAT via escape hatch |
| No GitHub App creation | **Pass** — render only |
| No SSM/AWS changes | **Pass** |

---

## Independence from PR #33

| PR | Scope |
|----|-------|
| PR #33 | Filesystem path `crypto-2.0` |
| This branch | GitHub auth transition render + docs |

No overlap in file hunks except `verify_deploy_secrets.sh` and `runtime.env.example` where PR #33 touched path-only lines and this branch adds auth lines.

---

## Review verdict

**APPROVED for commit** on `feat/github-app-transition-mode` after PR #33 merges.
