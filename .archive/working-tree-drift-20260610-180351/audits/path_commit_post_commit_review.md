# Path Commit Post-Commit Review

**Date:** 2026-06-09  
**Branch:** `fix/path-canonicalization-prod`  
**Pushed:** No

---

## Commit hash

```
cb175c23f44a8a3c2389ba9f9af84cf46a119877
```

Short: `cb175c2`

**Title:** `fix(deploy): canonicalize production repo path to crypto-2.0`

---

## Files included (13)

| File | Change |
|------|--------|
| `.github/workflows/deploy_session_manager.yml` | SSM `cd` → crypto-2.0 |
| `.github/workflows/deploy.yml` | SSH/rsync → crypto-2.0 |
| `deploy_all.sh` | SSM `cd` → crypto-2.0 |
| `deploy_aws.sh` | `REMOTE_DIR` + heredoc → crypto-2.0 |
| `deploy_github_token_ssm.sh` | `PROJECT_DIR=crypto-2.0` |
| `restart_backend_ssm.sh` | SSM `cd` → crypto-2.0 |
| `scripts/aws/deploy_all_manual_commands.sh` | Heredoc `cd` |
| `scripts/aws/inject_aws_creds_to_prod.sh` | SSM paths |
| `scripts/aws/push_runtime_env_to_ec2.sh` | secrets path + restart cwd |
| `scripts/deploy_production.sh` | `REMOTE_PROJECT_DIR` default |
| `backend/app/services/atp_ssm_runner.py` | `_ATP_PROJECT_PATH` |
| `scripts/verify_deploy_secrets.sh` | Line 9 comment only |
| `secrets/runtime.env.example` | Line 112 `ATP_PROJECT_PATH` only |

**Stats:** 13 files, 32 insertions(+), 32 deletions(-)

---

## Files excluded (preserved uncommitted for GitHub App phase)

| File | Reason |
|------|--------|
| `scripts/aws/render_runtime_env.sh` | ALLOW_LEGACY auto-write |
| `backend/docs/GITHUB_APP_AUTH.md` | Transition documentation |
| `scripts/verify_deploy_secrets.sh` | auth_mode output (lines 70–75) |
| `secrets/runtime.env.example` | GitHub auth comments (lines 94–102) |

---

## Rollback plan

1. `git revert cb175c2` on branch (operator action)
2. No database, Docker image, or SSM changes involved
3. **Warning:** Reverting re-breaks CI on crypto-2.0-only PROD
4. Emergency symlink (temporary):  
   `ln -sfn /home/ubuntu/crypto-2.0 /home/ubuntu/automated-trading-platform`

---

## Deployment impact

| Item | Effect |
|------|--------|
| **When active** | After merge to `main` + push (not done yet) |
| **CI trigger** | `deploy_session_manager.yml` on push to main |
| **Change** | Deploy/git pull/secrets write in `/home/ubuntu/crypto-2.0` |
| **Downtime** | Standard rebuild window only |
| **Auth** | Unchanged by this commit |
| **Trading** | Unchanged |

---

## Risk assessment

| Area | Level |
|------|-------|
| Overall | **Low** |
| CI deploy alignment | **High benefit / low regression** |
| Secrets path correction | **High benefit** |
| Unrelated system impact | **None** |

**Verdict: GO for PR review and merge (operator approval required)**

---

## Next steps for reviewer

1. Review diff: `git show cb175c2`
2. Confirm no auth/trading/schema changes
3. Open PR from `fix/path-canonicalization-prod` (operator)
4. After merge: verify EC2 deploy lands in `crypto-2.0`
5. Proceed with GitHub App transition commit (4 uncommitted files)
