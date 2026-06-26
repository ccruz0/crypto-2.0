# Split Verification — Path vs GitHub App

**Date:** 2026-06-09  
**Branch:** `fix/path-canonicalization-prod`  
**Path commit:** `cb175c2`

---

## Split method

1. Created branch `fix/path-canonicalization-prod`
2. Restored auth-only whole files to HEAD (`render_runtime_env.sh`, `GITHUB_APP_AUTH.md`)
3. Reduced MIXED files to path-only hunks before staging
4. Committed 13 path files
5. Re-applied GitHub App changes to working tree (uncommitted)

---

## Path commit contents (verified)

| File | In commit? | Path only? |
|------|------------|------------|
| `.github/workflows/deploy_session_manager.yml` | Yes | Yes |
| `.github/workflows/deploy.yml` | Yes | Yes |
| `deploy_all.sh` | Yes | Yes |
| `deploy_aws.sh` | Yes | Yes |
| `deploy_github_token_ssm.sh` | Yes | Yes |
| `restart_backend_ssm.sh` | Yes | Yes |
| `scripts/aws/deploy_all_manual_commands.sh` | Yes | Yes |
| `scripts/aws/inject_aws_creds_to_prod.sh` | Yes | Yes |
| `scripts/aws/push_runtime_env_to_ec2.sh` | Yes | Yes |
| `scripts/deploy_production.sh` | Yes | Yes |
| `backend/app/services/atp_ssm_runner.py` | Yes | Yes |
| `scripts/verify_deploy_secrets.sh` | Yes (line 9 comment only) | Yes |
| `secrets/runtime.env.example` | Yes (line 112 only) | Yes |

### Excluded from path commit (verified absent in `git show cb175c2`)

| File / change | Category |
|---------------|----------|
| `scripts/aws/render_runtime_env.sh` ALLOW_LEGACY block | GITHUB_APP |
| `backend/docs/GITHUB_APP_AUTH.md` transition section | GITHUB_APP |
| `scripts/verify_deploy_secrets.sh` auth_mode output | GITHUB_APP |
| `secrets/runtime.env.example` GitHub auth comments (94–102) | GITHUB_APP |

---

## Verification checks

| Check | Result |
|-------|--------|
| Path changes only in commit | **PASS** |
| No auth logic in commit | **PASS** |
| No GitHub App handling in commit | **PASS** |
| No ALLOW_LEGACY in commit | **PASS** |
| No render_runtime_env changes in commit | **PASS** |
| No secret value changes | **PASS** |
| Auth changes preserved in working tree | **PASS** (4 files modified, unstaged) |
| Auth changes not deleted | **PASS** |

---

## Working tree after split (GitHub App phase — uncommitted)

```
 M backend/docs/GITHUB_APP_AUTH.md
 M scripts/aws/render_runtime_env.sh
 M scripts/verify_deploy_secrets.sh
 M secrets/runtime.env.example
```

Diff: 4 files, 51 insertions(+), 4 deletions(-)

Ready for separate branch/commit: `fix/github-app-legacy-transition-render` or new branch from current HEAD.
