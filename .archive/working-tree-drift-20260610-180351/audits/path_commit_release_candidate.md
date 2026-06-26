# Path Commit Release Candidate Review

**Date:** 2026-06-09  
**Commit:** `cb175c23f44a8a3c2389ba9f9af84cf46a119877` (`cb175c2`)  
**Title:** `fix(deploy): canonicalize production repo path to crypto-2.0`  
**Reviewer role:** Production-impact / release candidate  
**Production fact:** Verified running from `/home/ubuntu/crypto-2.0`

---

## Phase 1 — Per-file constraint verification

| File | Change type | Auth | GitHub App | render_runtime_env | Docker | Compose | OpenClaw | Trading |
|------|-------------|------|------------|-------------------|--------|---------|----------|---------|
| `.github/workflows/deploy_session_manager.yml` | SSM `cd` paths (3 lines) | None | None | None | None | None | None | None |
| `.github/workflows/deploy.yml` | SSH/rsync `cd` paths + comments | None | None | None | None | None | None | None |
| `deploy_all.sh` | SSM `cd` paths (3 lines) | None* | None* | None | None | None | None | None |
| `deploy_aws.sh` | `REMOTE_DIR` + heredoc `cd` | None | None | None | None | None | None | None |
| `deploy_github_token_ssm.sh` | `PROJECT_DIR` variable | None* | None* | None | None | None | None | None |
| `restart_backend_ssm.sh` | SSM `cd` | None | None | None | None | None | None | None |
| `scripts/aws/deploy_all_manual_commands.sh` | Heredoc `cd` | None | None | None | None | None | None | None |
| `scripts/aws/inject_aws_creds_to_prod.sh` | SSM `cd` (2 lines) | None | None | None | None | None | None | None |
| `scripts/aws/push_runtime_env_to_ec2.sh` | Absolute secrets path + restart cwd | None | None | None | None | None | None | None |
| `scripts/deploy_production.sh` | `REMOTE_PROJECT_DIR` default | None | None | None | None | None | None | None |
| `backend/app/services/atp_ssm_runner.py` | Docstring + `_ATP_PROJECT_PATH` | None | None | None | None | None | None | None |
| `scripts/verify_deploy_secrets.sh` | Comment line 9 only | None | None | None | None | None | None | None |
| `secrets/runtime.env.example` | `ATP_PROJECT_PATH` comment line 112 | None | None | None | None | None | None | None |

\*Pre-existing GITHUB_TOKEN inject/fetch logic unchanged; only filesystem `cd` target changed.

**Phase 1 verdict: PASS** — 32 line substitutions, 32 deletions; zero logic changes in excluded categories.

---

## Phase 2 — Deployment script execution simulation

Assumed PROD layout (verified): `/home/ubuntu/crypto-2.0` is git clone with `docker-compose.yml`, `secrets/`, `scripts/`.

### Primary CI path — `deploy_session_manager.yml`

| Step | Simulated flow | Resolves correctly? |
|------|----------------|---------------------|
| 1 PAT inject | `cd /home/ubuntu/crypto-2.0 \|\| cd ~/crypto-2.0` → writes `.env.aws`, `secrets/runtime.env` | **Yes** — relative paths valid after cd |
| 2 Git pull | `cd ~/crypto-2.0 \|\| cd /home/ubuntu/crypto-2.0` → `git pull`, clone frontend | **Yes** — repo root |
| 3 Rebuild | same cd → `render_runtime_env.sh` → `docker compose --profile aws ...` | **Yes** — compose file at repo root |

**Checks:**
- Target directory exists on PROD: **Yes** (verified)
- `docker-compose.yml` at cwd: **Yes** (standard layout)
- `secrets/runtime.env` path: **Yes** — `secrets/runtime.env` relative to repo root after cd
- Docker compose cwd: **Yes** — all compose invocations after successful cd

### `deploy_all.sh`

Mirrors CI SSM flow above. **PASS** — identical path resolution.

### `deploy_aws.sh`

| Step | Flow | Result |
|------|------|--------|
| Local | rsync/scp to `$REMOTE_DIR` default `/home/ubuntu/crypto-2.0` | **Yes** |
| Remote PERM_FIX | `cd /home/ubuntu/crypto-2.0 \|\| exit 1` | **Yes** |
| Remote deploy | `cd /home/ubuntu/crypto-2.0` → `docker compose --profile aws` | **Yes** |

**Note:** SSH heredocs hardcode path; ignore `REMOTE_DIR` override. Low risk — default matches PROD.

### `push_runtime_env_to_ec2.sh`

| Command | Path |
|---------|------|
| Write secrets | `/home/ubuntu/crypto-2.0/secrets/runtime.env` |
| Restart | `cd /home/ubuntu/crypto-2.0 && docker compose ...` |

**PASS** — previously wrote to wrong tree; fix is corrective.

### `inject_aws_creds_to_prod.sh`

SSM: `cd /home/ubuntu/crypto-2.0` → mutate `secrets/runtime.env`. **PASS**

### `deploy_github_token_ssm.sh`

SSM: `cd /home/ubuntu/$PROJECT_DIR` where `PROJECT_DIR=crypto-2.0`. **PASS**

### `restart_backend_ssm.sh`

SSM: `cd ~/crypto-2.0` → `docker compose --profile aws restart`. **PASS** (cd failure would fail compose — pre-existing pattern)

### `atp_ssm_runner.py`

SSM commands prefixed with `cd /home/ubuntu/crypto-2.0 &&`. **PASS**

### Local filesystem validation (this host)

```
/home/ubuntu/crypto-2.0          → exists
/home/ubuntu/crypto-2.0/docker-compose.yml → exists
/home/ubuntu/crypto-2.0/secrets/ → exists
```

---

## Phase 3 — Workflow analysis

| Workflow | Trigger | Production critical? | Legacy filesystem path after commit? |
|----------|---------|---------------------|----------------------------------------|
| `deploy_session_manager.yml` | `push: main`, `workflow_dispatch` | **YES — primary** | **No** — all `cd` use `crypto-2.0` |
| `deploy.yml` | `workflow_dispatch` only | No (legacy SSH) | **No** — all targets `crypto-2.0` |

**Remaining `automated-trading-platform` in commit-changed deploy files:**
- SSM parameter names only (`/automated-trading-platform/prod/github_token`, etc.) — **intentional AWS resource names, not filesystem paths**
- Docker container name filter in `verify_deploy_secrets.sh` line 19 — **unchanged, container naming not path**

### Can `deploy_session_manager.yml` still fail on path assumptions?

| Failure mode | Path-related? | Status after commit |
|--------------|---------------|---------------------|
| `Cannot find project directory` | **Yes** | **Resolved** if PROD has `crypto-2.0` |
| Both `~/crypto-2.0` and `/home/ubuntu/crypto-2.0` missing | Yes | Would fail — contradicts verified PROD |
| SSM user ≠ ubuntu, `~` resolves elsewhere | Low | Mitigated by absolute path fallback |
| Frontend version `0.46` gate | No | Pre-existing |
| `git pull` soft-continue | No | Pre-existing |
| `render_runtime_env.sh` failure | No | Pre-existing (continues) |

**Path-specific failure risk: LOW** (was HIGH before commit).

---

## Scoring

| Metric | Score | Rationale |
|--------|-------|-----------|
| **Risk score (0–10)** | **2** | Mechanical path swap; aligns with verified PROD; no runtime logic change. Residual: uncommitted auth phase, Tier-2 scripts. |
| **Rollback complexity (0–10)** | **1** | Single `git revert`; no migrations, no SSM renames, no image changes. Revert re-breaks deploy on crypto-2.0-only PROD. |
| **Deployment confidence (0–100%)** | **88%** | High confidence path alignment fixes primary deploy blocker. −12% for pre-existing non-path risks (frontend gate, auth transition not in commit). |

---

## Remaining blockers (outside this commit)

1. **GitHub App transition** — uncommitted `render_runtime_env.sh` ALLOW_LEGACY patch; PAT-only may fail post-restart until separate commit
2. **Tier-2 ops scripts** — `update_telegram_menu_aws_ssm.sh`, `update_coins_aws_ssm.sh`, etc. still legacy-only
3. **Documentation drift** — runbooks reference legacy path in places

None block merge of this path-only commit.

---

## GO / NO-GO

| Gate | Decision |
|------|----------|
| Safe for production merge? | **GO** |
| Safe for deploy after merge to main? | **GO** |
| Complete repo path migration? | **NO-GO** (Tier-2+ remain) |
| Resolves all deploy failures? | **NO-GO** (auth/frontend pre-existing) |

**Release candidate verdict: GO**

---

## Recommended post-merge verification (operator)

```bash
# After CI deploy completes on EC2
cd /home/ubuntu/crypto-2.0 && pwd
test -f docker-compose.yml && echo compose_ok
docker compose --profile aws ps
curl -sf http://localhost:8002/ping_fast && echo backend_ok
```
