# GitHub App Transition Commit Set

**Date:** 2026-06-09  
**Proposed title:** `feat(deploy): auto-set ALLOW_LEGACY_GITHUB_PAT during GitHub App transition`

*(Alternative title aligned with PR #32: `fix(auth): render ALLOW_LEGACY_GITHUB_PAT when PAT-only on AWS`)*

---

## Exact files (3 whole + 2 partial hunks)

### Whole files

| # | File | Changed lines | Purpose |
|---|------|---------------|---------|
| 1 | `scripts/aws/render_runtime_env.sh` | 254–282 | Auto-write/remove `ALLOW_LEGACY_GITHUB_PAT`; emit `GITHUB_AUTH_MODE` |
| 2 | `backend/docs/GITHUB_APP_AUTH.md` | 62–68 | Document transition behavior for operators |

### Partial hunks (from MIXED files)

| File | Hunk | Purpose |
|------|------|---------|
| `scripts/verify_deploy_secrets.sh` | Lines 70–74 | Print `auth_mode: github_app \| legacy_transition \| none` |
| `secrets/runtime.env.example` | Lines 94–102 | Document GitHub App keys, PAT fallback, `ALLOW_LEGACY_GITHUB_PAT` |

---

## Exact purpose

### Problem solved

After PR #32 merged, the backend **blocks** PAT-only GitHub API usage on AWS unless `ALLOW_LEGACY_GITHUB_PAT=true` is in `secrets/runtime.env` (see `backend/app/factory.py`).

PROD currently has:

- SSM `github_token` — **present**
- SSM `github_app/*` — **absent**

Without this commit, `render_runtime_env.sh` writes `GITHUB_TOKEN` but **not** `ALLOW_LEGACY_GITHUB_PAT`, causing deploy dispatch and Cursor bridge failures after backend restart.

### What this commit does

| Condition after render | Action |
|------------------------|--------|
| All three `GITHUB_APP_*` in runtime.env | Remove `ALLOW_LEGACY_GITHUB_PAT`; mode = `github_app` |
| `GITHUB_TOKEN` present, App incomplete | Set `ALLOW_LEGACY_GITHUB_PAT=true`; mode = `legacy_transition` |
| Neither | Remove `ALLOW_LEGACY_GITHUB_PAT`; mode = `none` |

### What this commit does NOT do

- Does not create GitHub App in GitHub
- Does not write App credentials to SSM
- Does not change Python auth logic (already in PR #32 / `main`)
- Does not change deploy filesystem paths

---

## Dependency on PR #32

| Dependency | Required? | Notes |
|------------|-----------|-------|
| PR #32 merged to `main` | **Yes** | Backend enforces App-or-legacy-PAT gate |
| `backend/app/factory.py` startup check | **Yes** | Reads `ALLOW_LEGACY_GITHUB_PAT` |
| `backend/app/services/github_app_auth.py` | **Yes** | Token resolution logic |
| Path canonicalization | **No hard dependency** | Auth render runs wherever deploy `cd`s; **path fix should land first or concurrently** so render executes on live tree |
| GitHub App installed on repo | **No** — this commit supports **pre-App** transition | App SSM provisioning is follow-on work |
| SSM App parameters populated | **No** — enables PAT fallback until they exist |

---

## Deployment prerequisites

| Prerequisite | Status | Action if missing |
|--------------|--------|-------------------|
| Deploy runs from `/home/ubuntu/crypto-2.0` | Required | Path commit first (or already on PROD manually) |
| `render_runtime_env.sh` invoked during deploy | **Yes** — in `deploy_session_manager.yml` step | None |
| SSM `/automated-trading-platform/prod/github_token` | Present on PROD | None |
| Backend container recreated after render | **Yes** — deploy rebuilds | None |
| Operator understands legacy PAT is temporary | Recommended | Revoke PAT after App cutover |

### Post-merge verification

```bash
cd /home/ubuntu/crypto-2.0
bash scripts/aws/render_runtime_env.sh
grep ALLOW_LEGACY_GITHUB_PAT secrets/runtime.env
./scripts/verify_deploy_secrets.sh
# Expect: auth_mode: legacy_transition (until App SSM exists)
```

---

## Risk

| Area | Risk | Notes |
|------|------|-------|
| Auto-enabling legacy PAT | **Low–Medium** | Intentional transition escape hatch; removes manual step |
| Accidental PAT retention after App cutover | **Low** | Render removes flag when all App keys present |
| Running before path fix | **Medium** | Render may run on wrong cwd if legacy path empty |

---

## Staging command reference (operator — do not run automatically)

```bash
cd /home/ubuntu/crypto-2.0

git add scripts/aws/render_runtime_env.sh backend/docs/GITHUB_APP_AUTH.md
git add -p scripts/verify_deploy_secrets.sh    # auth_mode block only
git add -p secrets/runtime.env.example         # GitHub comments only (lines 94–102)

git diff --cached -- scripts/aws/render_runtime_env.sh  # should show auth block
```
