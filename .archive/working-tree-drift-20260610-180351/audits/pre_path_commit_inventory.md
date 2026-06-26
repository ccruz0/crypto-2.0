# Pre Path Commit Inventory

**Date:** 2026-06-09  
**Repository:** `/home/ubuntu/crypto-2.0`  
**Source branch (before split):** `fix/github-app-legacy-transition-render`  
**Target branch (created):** `fix/path-canonicalization-prod`

---

## Branch name

```
fix/path-canonicalization-prod
```

Created locally from `fix/github-app-legacy-transition-render`. **Not pushed.**

---

## Git status (before path commit)

```
On branch fix/github-app-legacy-transition-render
Changes not staged for commit: 15 modified tracked files
Untracked: audit docs, agent notes, runbooks
Staged: none
```

---

## Modified files (pre-commit, all 15)

| File | Lines changed |
|------|---------------|
| `.github/workflows/deploy.yml` | 22 |
| `.github/workflows/deploy_session_manager.yml` | 6 |
| `backend/app/services/atp_ssm_runner.py` | 4 |
| `backend/docs/GITHUB_APP_AUTH.md` | 8 |
| `deploy_all.sh` | 6 |
| `deploy_aws.sh` | 6 |
| `deploy_github_token_ssm.sh` | 2 |
| `restart_backend_ssm.sh` | 2 |
| `scripts/aws/deploy_all_manual_commands.sh` | 2 |
| `scripts/aws/inject_aws_creds_to_prod.sh` | 4 |
| `scripts/aws/push_runtime_env_to_ec2.sh` | 4 |
| `scripts/aws/render_runtime_env.sh` | 31 |
| `scripts/deploy_production.sh` | 2 |
| `scripts/verify_deploy_secrets.sh` | 8 |
| `secrets/runtime.env.example` | 12 |

**Diff summary:** 15 files, 83 insertions(+), 36 deletions(-)

---

## Staged files (pre-commit)

None.

---

## Untracked files (pre-commit, representative)

| Path | Type |
|------|------|
| `docs/audits/*.md` | Audit artifacts |
| `docs/runbooks/GITHUB_APP_CREATION_AND_CUTOVER.md` | Runbook |
| `docs/agents/generated-notes/*` | Agent notes |

---

## Post-commit state (after Phase 7)

| Item | Value |
|------|-------|
| Commit | `cb175c23f44a8a3c2389ba9f9af84cf46a119877` |
| Files in commit | 13 |
| Staged | none |
| Uncommitted (GitHub App phase) | 4 files |
| Untracked | audit docs + `.local/path-split-backup/` |
