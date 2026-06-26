# GitHub App Transition — Commit Plan

**Date:** 2026-06-09  
**Branch:** `feat/github-app-transition-mode`  
**Base commit:** `cb175c23f44a8a3c2389ba9f9af84cf46a119877` (same as PR #33 head)  
**Prerequisite:** PR #33 merged to `main`  
**Status:** Prepared — **not committed, not pushed**

---

## Files to commit (4)

| # | File | Purpose |
|---|------|---------|
| 1 | `scripts/aws/render_runtime_env.sh` | Auto `ALLOW_LEGACY_GITHUB_PAT=true` when PAT-only |
| 2 | `backend/docs/GITHUB_APP_AUTH.md` | Operator transition documentation |
| 3 | `scripts/verify_deploy_secrets.sh` | `auth_mode:` diagnostic output |
| 4 | `secrets/runtime.env.example` | GitHub App / PAT / ALLOW_LEGACY comments |

**Do not include:** Path migration files (already in PR #33), audit docs (optional separate commit), `.local/` backup.

---

## Expected commit message

```
feat(deploy): enable GitHub App transition mode

When render_runtime_env.sh writes GITHUB_TOKEN but not all three
GITHUB_APP_* values, automatically set ALLOW_LEGACY_GITHUB_PAT=true
so PAT-only production keeps working after PR #32 until GitHub App
credentials exist in SSM.

Adds auth_mode diagnostics to verify_deploy_secrets.sh and documents
transition behavior in GITHUB_APP_AUTH.md and runtime.env.example.

Requires PR #33 (path canonicalization) merged first so render runs
on /home/ubuntu/crypto-2.0. Does not create GitHub App or remove PAT.
```

Short title alternative: `feat(deploy): enable GitHub App transition mode`

---

## Staging commands (operator — when ready)

```bash
cd /home/ubuntu/crypto-2.0
git checkout feat/github-app-transition-mode
git add \
  scripts/aws/render_runtime_env.sh \
  backend/docs/GITHUB_APP_AUTH.md \
  scripts/verify_deploy_secrets.sh \
  secrets/runtime.env.example
git diff --cached --stat
# commit when PR #33 is merged
```

---

## Risk score

| Metric | Value |
|--------|-------|
| **Risk** | **3/10** |
| Rationale | Changes deploy-time env flags only; enables existing PAT path required by PR #32; auto-removes flag when App keys appear |

**Higher than path commit (2/10)** because it modifies runtime.env auth flags on every deploy render.

---

## Rollback

1. Revert transition commit on `main`.
2. Manually add `ALLOW_LEGACY_GITHUB_PAT=true` to EC2 `secrets/runtime.env` if backend must stay up with PAT-only.
3. `docker compose --profile aws up -d --force-recreate backend-aws`
4. No SSM changes required.

---

## Required future actions (after this commit)

| # | Action | Owner |
|---|--------|-------|
| 1 | Merge PR #33 (path) first | Operator |
| 2 | Merge this transition PR | Operator |
| 3 | Verify post-deploy: `./scripts/verify_deploy_secrets.sh` → `auth_mode: legacy_transition` | Operator |
| 4 | Create GitHub App on `ccruz0/crypto-2.0` | Operator |
| 5 | Store SSM `/automated-trading-platform/prod/github_app/*` | Operator |
| 6 | Re-render + redeploy → verify `auth_mode: github_app` | Operator |
| 7 | Revoke PAT + delete SSM `github_token` (separate, after verification) | Operator |

---

## CI considerations

This commit touches **protected paths**:
- `secrets/runtime.env.example` (path-guard)
- Possibly `scripts/aws/render_runtime_env.sh` if listed

Expect **path-guard failure** — prepare override justification similar to PR #33.

---

## Merge order

```
1. PR #33 — path canonicalization
2. This PR — GitHub App transition mode
3. Future PR — GitHub App SSM provisioning / cutover (operator + docs)
```
