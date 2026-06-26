# Deployment Path Safety Review

**Date:** 2026-06-09  
**Verified PROD fact:** Running containers launched from `/home/ubuntu/crypto-2.0` (docker compose labels confirm).

---

## Deploy paths in use

| Mechanism | Trigger | Target path (patched) | Role |
|-----------|---------|----------------------|------|
| **`deploy_session_manager.yml`** | `push: main`, `workflow_dispatch` | `/home/ubuntu/crypto-2.0` | **Primary — single source of truth** |
| **`deploy_all.sh`** | Manual (mirrors CI) | `/home/ubuntu/crypto-2.0` | Operator fallback |
| **`deploy.yml`** | `workflow_dispatch` only | `/home/ubuntu/crypto-2.0` | Legacy SSH/rsync |
| **`deploy_aws.sh`** | Manual SSH | `/home/ubuntu/crypto-2.0` (default `REMOTE_DIR`) | Legacy SSH helper |
| **`scripts/deploy_production.sh`** | Manual | `/home/ubuntu/crypto-2.0` (default) | Pre-flight + remote deploy |

### Primary deploy flow (CI)

```
push main
  → deploy_session_manager.yml
    → SSM inject GITHUB_TOKEN (cd crypto-2.0)
    → SSM git pull + frontend clone (cd crypto-2.0)
    → SSM render_runtime_env.sh + docker compose --profile aws (cd crypto-2.0)
```

Comment in `deploy.yml` line 2 confirms: *"Default deploy on push to main is deploy_session_manager.yml."*

---

## Is crypto-2.0 now canonical in deploy tooling?

### Tier-1 (patched in working tree) — **YES**

All production-critical deploy entry points now reference `crypto-2.0`:

- CI SSM workflow (3 `cd` steps)
- `deploy_all.sh` (3 steps)
- `push_runtime_env_to_ec2.sh` (secrets file path)
- `atp_ssm_runner.py` (agent command cwd)
- SSH/rsync workflows and scripts

### Tier-2 (not in current patch) — **legacy path remains**

These still reference `/home/ubuntu/automated-trading-platform` and can fail or no-op on crypto-2.0-only PROD:

| File | Risk |
|------|------|
| `update_telegram_menu_aws_ssm.sh` | Medium — ops script |
| `update_coins_aws_ssm.sh` | Medium — ops script |
| `verify_deployment.sh` | Low — verification |
| `backend/app/services/lab_ssm_runner.py` | Medium — LAB agent cwd |
| `backend/app/api/routes_admin.py` | Low — embedded diagnostic script |
| `scripts/verify_ec2_ip_and_health.sh` | Low — has fallback order |
| `scripts/ssm/run_atp_checks.sh` | Low — prefers crypto-2.0 first |
| Various diag/openclaw scripts | Low — default env vars |

**SSM parameter prefixes** (`/automated-trading-platform/prod/...`) are intentionally unchanged — they are AWS resource names, not filesystem paths.

**Docker container names** (`automated-trading-platform-backend-aws`) unchanged — not filesystem paths.

---

## Will any deploy step still fail after path patch?

### Fixed by patch (were broken on crypto-2.0-only PROD)

| Step | Previous failure | After patch |
|------|------------------|-------------|
| SSM git pull | `cd ~/automated-trading-platform` → exit 1 | Resolves `crypto-2.0` |
| SSM docker compose rebuild | Same | Resolves `crypto-2.0` |
| `push_runtime_env_to_ec2.sh` | Wrote to wrong secrets path | Writes to `crypto-2.0/secrets/` |
| `atp_ssm_runner` agent commands | Wrong cwd | Correct cwd |

### Remaining failure modes (not path-patch scope)

| Issue | Impact | Mitigation |
|-------|--------|------------|
| GitHub App SSM keys absent | Backend may reject PAT-only without `ALLOW_LEGACY_GITHUB_PAT` | Requires `render_runtime_env.sh` auth patch **or** manual flag |
| Frontend version gate (`0.46`) | Deploy fails if frontend clone wrong version | Pre-existing; unrelated to path |
| Git pull soft-fail | Workflow continues on pull failure | Pre-existing behavior |
| Tier-2 ops scripts unpatched | Manual ops from legacy scripts fail | Future PR or symlink on EC2 |

---

## Fallback logic remaining

| Location | Fallback pattern | Assessment |
|----------|------------------|------------|
| SSM workflows | `cd ~/crypto-2.0 \|\| cd /home/ubuntu/crypto-2.0` | **Good** — home vs absolute |
| `deploy_session_manager.yml` PAT inject | `\|\| true` (non-fatal cd) | Acceptable |
| SSM github_token fetch | `/automated-trading-platform/prod/github_token` then `/openclaw/github-token` | **Intentional** — SSM naming, not path |
| `scripts/ssm/run_atp_checks.sh` | crypto-2.0 first, then legacy | **Not updated** — still safe (prefers canonical) |
| Runbooks / docs | Many still document legacy path | Docs drift — non-blocking for deploy |

**No filesystem fallback to `automated-trading-platform` remains in Tier-1 deploy files after patch.**

---

## deploy_aws.sh / deploy.yml specifics

- **`deploy_aws.sh`**: Uses `$REMOTE_DIR` for mkdir/scp/rsync but hardcodes `cd /home/ubuntu/crypto-2.0` in SSH heredocs (lines 161, 180). Override via `REMOTE_DIR` env for scp target only; heredocs ignore override — minor inconsistency, low risk if default is correct.
- **`deploy.yml`**: Targets EC2 via `EC2_HOST` secret (atp-rebuild-2026). Not auto-triggered. Safe after path patch for manual SSH deploys.

---

## Safety conclusion

| Question | Answer |
|----------|--------|
| Primary deploy path aligned with PROD? | **Yes**, after Tier-1 patch merges |
| crypto-2.0 canonical in CI? | **Yes** |
| Any Tier-1 step still targets legacy path? | **No** (in working tree) |
| Full repo path-clean? | **No** — Tier-2 scripts and docs remain |
| Deploy safe without auth patch? | **Partial** — path works; PAT-only auth may still fail until `ALLOW_LEGACY` is set |
