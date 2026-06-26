# Change Set Split Classification

**Date:** 2026-06-09  
**Repository:** `/home/ubuntu/crypto-2.0`  
**Branch:** `fix/github-app-legacy-transition-render`  
**Modified tracked files:** 15

## Classification table

| File | Category | Notes |
|------|----------|-------|
| `.github/workflows/deploy.yml` | **PATH** | All 11 hunks: `automated-trading-platform` → `crypto-2.0` in comments, mkdir, cd, rsync, ssh |
| `.github/workflows/deploy_session_manager.yml` | **PATH** | Lines 68, 88, 146: SSM `cd` targets only |
| `backend/app/services/atp_ssm_runner.py` | **PATH** | Docstring + `_ATP_PROJECT_PATH` constant |
| `backend/docs/GITHUB_APP_AUTH.md` | **GITHUB_APP** | New "Transition period" section (lines 62–68) |
| `deploy_all.sh` | **PATH** | SSM `cd` commands (lines 51, 73, 100) |
| `deploy_aws.sh` | **PATH** | `REMOTE_DIR` default + SSH heredoc `cd` |
| `deploy_github_token_ssm.sh` | **PATH** | `PROJECT_DIR` variable |
| `restart_backend_ssm.sh` | **PATH** | SSM `cd` command |
| `scripts/aws/deploy_all_manual_commands.sh` | **PATH** | Heredoc operator `cd` |
| `scripts/aws/inject_aws_creds_to_prod.sh` | **PATH** | SSM command `cd` paths |
| `scripts/aws/push_runtime_env_to_ec2.sh` | **PATH** | EC2 secrets file path + docker restart cwd |
| `scripts/aws/render_runtime_env.sh` | **GITHUB_APP** | Lines 254–282: `ALLOW_LEGACY_GITHUB_PAT` auto-write, `GITHUB_AUTH_MODE` detection |
| `scripts/deploy_production.sh` | **PATH** | `REMOTE_PROJECT_DIR` default |
| `scripts/verify_deploy_secrets.sh` | **MIXED** | Line 9 comment = PATH; lines 70–74 `auth_mode` output = GITHUB_APP |
| `secrets/runtime.env.example` | **MIXED** | Lines 94–102 GitHub App/PAT comments = GITHUB_APP; line 112 `ATP_PROJECT_PATH` = PATH |

## Counts

| Category | Files |
|----------|-------|
| PATH | 11 |
| GITHUB_APP | 3 |
| MIXED | 2 |
| **Total** | **15** |

## MIXED file split instructions

These files require **partial staging** (`git add -p`) or two sequential edits/commits:

### `scripts/verify_deploy_secrets.sh`

| Hunk | Commit set |
|------|------------|
| Line 9: `cd ~/crypto-2.0` in comment | PATH |
| Lines 70–74: `auth_mode:` print block | GITHUB_APP |

### `secrets/runtime.env.example`

| Hunk | Commit set |
|------|------------|
| Lines 94–102: GitHub App / PAT / `ALLOW_LEGACY` documentation | GITHUB_APP |
| Line 112: `ATP_PROJECT_PATH=/home/ubuntu/crypto-2.0` | PATH |

## Untracked files (not in either commit set)

Audit docs, agent notes, and runbooks under `docs/` are **out of scope** for both commits unless explicitly added by operator.

## Independence check

| Set | Touches auth/runtime? | Touches deploy path? |
|-----|----------------------|----------------------|
| PATH (11 + 2 partial hunks) | **No** | **Yes** |
| GITHUB_APP (3 + 2 partial hunks) | **Yes** | **No** (except example comment on line 9 of verify script) |

The two sets can be committed and merged **in either order** without merge conflicts (disjoint hunks in MIXED files).
