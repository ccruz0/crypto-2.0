# Path-Only Commit Set

**Date:** 2026-06-09  
**Proposed title:** `fix(deploy): canonicalize production repo path to crypto-2.0`

---

## Exact files (11 whole + 2 partial hunks)

### Whole files

| # | File | Changed lines (approx.) |
|---|------|-------------------------|
| 1 | `.github/workflows/deploy_session_manager.yml` | 68, 88, 146 |
| 2 | `.github/workflows/deploy.yml` | 19–21, 166–168, 176, 194, 201, 214, 222 |
| 3 | `deploy_all.sh` | 51, 73, 100 |
| 4 | `deploy_aws.sh` | 33, 161, 180 |
| 5 | `deploy_github_token_ssm.sh` | 9 |
| 6 | `restart_backend_ssm.sh` | 26 |
| 7 | `scripts/aws/deploy_all_manual_commands.sh` | 14 |
| 8 | `scripts/aws/inject_aws_creds_to_prod.sh` | 32, 60 |
| 9 | `scripts/aws/push_runtime_env_to_ec2.sh` | 58–59 |
| 10 | `scripts/deploy_production.sh` | 24 |
| 11 | `backend/app/services/atp_ssm_runner.py` | 9, 24 |

### Partial hunks (from MIXED files)

| File | Hunk | Change |
|------|------|--------|
| `secrets/runtime.env.example` | Line 112 only | `ATP_PROJECT_PATH=/home/ubuntu/crypto-2.0` |
| `scripts/verify_deploy_secrets.sh` | Line 9 comment only | SSM example uses `cd ~/crypto-2.0` |

---

## Verification checklist

| Check | Result |
|-------|--------|
| No auth logic changes | **Pass** — no Python/shell auth branching |
| No GitHub App changes | **Pass** — no `GITHUB_APP_*` handling |
| No runtime.env render changes | **Pass** — `render_runtime_env.sh` excluded |
| No `ALLOW_LEGACY_GITHUB_PAT` changes | **Pass** — not in this set |
| No trading logic | **Pass** |
| No OpenClaw / Jarvis changes | **Pass** |
| No schema / Docker / compose changes | **Pass** |
| SSM parameter paths unchanged | **Pass** — `/automated-trading-platform/prod/...` retained |

---

## Exact risk

| Area | Risk | Rationale |
|------|------|-----------|
| CI deploy (`deploy_session_manager.yml`) | **Low** | Fixes fatal `cd` mismatch with verified PROD layout |
| Manual deploy (`deploy_all.sh`) | **Low** | Same path alignment |
| Secrets push (`push_runtime_env_to_ec2.sh`) | **Low–Medium impact / Low regression** | Was writing to wrong tree; fix is corrective |
| ATP SSM runner | **Low** | Agent commands run in correct cwd |
| Legacy SSH deploy | **Low** | Manual `workflow_dispatch` only |
| Rollback complexity | **Low** | String revert; no migrations |

**Overall: Low risk**

---

## Deployment impact

| Item | Effect |
|------|--------|
| **Trigger** | Merge to `main` → `deploy_session_manager.yml` runs |
| **Behavior change** | SSM steps `cd` into `/home/ubuntu/crypto-2.0` instead of legacy path |
| **Secrets** | `push_runtime_env_to_ec2.sh` writes to correct `secrets/runtime.env` |
| **Containers** | Same `docker compose --profile aws` flow; correct source tree |
| **Downtime** | None beyond existing rebuild window |
| **Auth state** | Unchanged — this commit does not set `ALLOW_LEGACY_GITHUB_PAT` |

### Post-merge operator checks

```bash
# On EC2 (via SSM or SSH)
cd /home/ubuntu/crypto-2.0 && pwd && git rev-parse --short HEAD
docker compose --profile aws ps
curl -sf http://localhost:8002/ping_fast
```

---

## Rollback

1. Revert commit or restore path strings to `automated-trading-platform`.
2. No DB migration, no image tag change required.
3. **Caution:** Reverting on crypto-2.0-only PROD re-breaks CI deploy (legacy path does not exist).
4. Emergency EC2 symlink (temporary only):  
   `ln -sfn /home/ubuntu/crypto-2.0 /home/ubuntu/automated-trading-platform`

---

## Staging command reference (operator — do not run automatically)

```bash
cd /home/ubuntu/crypto-2.0

# Stage whole path files
git add \
  .github/workflows/deploy.yml \
  .github/workflows/deploy_session_manager.yml \
  backend/app/services/atp_ssm_runner.py \
  deploy_all.sh deploy_aws.sh deploy_github_token_ssm.sh \
  restart_backend_ssm.sh \
  scripts/aws/deploy_all_manual_commands.sh \
  scripts/aws/inject_aws_creds_to_prod.sh \
  scripts/aws/push_runtime_env_to_ec2.sh \
  scripts/deploy_production.sh

# Stage partial hunks interactively
git add -p scripts/verify_deploy_secrets.sh    # line 9 comment only
git add -p secrets/runtime.env.example         # line 112 only

# Verify staged diff excludes auth changes
git diff --cached -- scripts/aws/render_runtime_env.sh  # should be empty
```
