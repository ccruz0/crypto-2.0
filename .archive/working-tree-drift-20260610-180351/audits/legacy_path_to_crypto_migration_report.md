# Legacy Path → Canonical Path Migration Report

**Date:** 2026-06-09  
**Legacy path:** `/home/ubuntu/automated-trading-platform` (and `~/automated-trading-platform`)  
**Canonical path:** `/home/ubuntu/crypto-2.0` (and `~/crypto-2.0`)  
**Evidence:** Repository grep; production canonical path per `docs/operations/BACKEND_AWS_CANONICAL_REPO.md`

**Excluded from this audit:** AWS SSM parameter prefixes (`/automated-trading-platform/prod/...`), Docker Compose project/container names (`automated-trading-platform-backend-aws`), Mac developer paths (`/Users/carloscruz/automated-trading-platform`).

---

## Workflows that WILL FAIL if legacy path absent on production

These reference **only** the legacy path with **no** `crypto-2.0` fallback. If PROD has only `/home/ubuntu/crypto-2.0`, they exit or no-op incorrectly.

| Workflow / script | Failure mode |
|-------------------|--------------|
| **`.github/workflows/deploy_session_manager.yml`** | Git pull + docker rebuild steps exit `1` at `Cannot find project directory`; push-to-main deploy **does not update live stack** |
| **`deploy_all.sh`** | Same as above (SSM mirror of session manager) |
| **`.github/workflows/deploy.yml`** | SSH/rsync targets `~/automated-trading-platform`; manual workflow deploy fails |
| **`restart_backend_ssm.sh`** | `cd ~/automated-trading-platform` only |
| **`update_telegram_menu_aws_ssm.sh`** | `cd /home/ubuntu/automated-trading-platform \|\| exit 1` |
| **`update_coins_aws_ssm.sh`** | `cd /home/ubuntu/automated-trading-platform` only |
| **`scripts/aws/inject_aws_creds_to_prod.sh`** | `cd ... \|\| exit 1` (legacy only) |
| **`scripts/aws/push_runtime_env_to_ec2.sh`** | Writes `runtime.env` to legacy path |
| **`deploy_github_token_ssm.sh`** | `PROJECT_DIR=automated-trading-platform` |
| **`scripts/aws/deploy_all_manual_commands.sh`** | Legacy-only `cd`, exits if missing |
| **`scripts/aws/deploy_generated_notes_fix_via_ssm.sh`** | Legacy-only `cd` |
| **`deploy_via_git.sh`**, **`deploy_tp_sl_fix_ssm.sh`**, **`deploy_quantity_fix_v2.sh`**, **`deploy_market_data_via_ssm.sh`**, **`deploy_telegram_fix_ssm.sh`**, **`deploy_useorders_fix.sh`**, **`deploy_orderstab.sh`**, **`DEPLOY_EXCHANGEORDER_FIX.sh`**, **`deploy_formatting_fixes.sh`**, **`deploy_lifecycle_events_fix.sh`**, **`deploy_backend_sltp_fix.sh`**, **`deploy_audit_via_ssm.sh`**, **`verify_deployment.sh`**, **`verify_code_in_container.sh`**, **`test_telegram_auth.sh`**, **`run_audit_via_ssm.sh`**, **`reset_telegram_updates.sh`** | Legacy path only in SSM/SSH commands |
| **`deploy_aws.sh`** | `REMOTE_DIR` default + SSH heredocs hardcoded to legacy |
| **`scripts/deploy_production.sh`** | `REMOTE_PROJECT_DIR` default legacy |
| **`backend/app/services/atp_ssm_runner.py`** | SSM `run-atp-command` cwd hardcoded legacy |
| **systemd unit files** under `scripts/selfheal/systemd/`, `scripts/health_monitor.service`, etc. | `WorkingDirectory` legacy — timers fail on boot if units installed |

### Workflows/scripts with dual fallback (survive today, try legacy first)

These **work on `crypto-2.0`-only PROD** only because they fall through to the second `cd`. They still hit the wrong tree first when both exist.

| File | Pattern |
|------|---------|
| `scripts/deploy_production_via_ssm.sh` | `cd legacy \|\| cd crypto` |
| `deploy_via_ssm.sh` | Same |
| `deploy_telegram_reliability_fix.sh` | `REPO=legacy; [ -d ] \|\| REPO=crypto` |
| `scripts/aws/fix_runtime_env_and_up_ssm.sh` | `cd legacy \|\| cd crypto` |
| `scripts/verify_ec2_ip_and_health.sh` | legacy first |
| `scripts/ssm/run_atp_checks.sh` | prefers `crypto-2.0` then legacy ✓ |

---

## Tier 1 — GitHub Actions (patched in minimal diff)

| File | Line | Current | Proposed | Risk |
|------|------|---------|----------|------|
| `.github/workflows/deploy_session_manager.yml` | 68 | `cd /home/ubuntu/automated-trading-platform \|\| cd ~/automated-trading-platform \|\| true` | `cd /home/ubuntu/crypto-2.0 \|\| cd ~/crypto-2.0 \|\| true` | **Low** — PAT inject step; non-fatal |
| `.github/workflows/deploy_session_manager.yml` | 88 | `cd ~/automated-trading-platform \|\| cd /home/ubuntu/automated-trading-platform \|\| { ... exit 1; }` | `cd ~/crypto-2.0 \|\| cd /home/ubuntu/crypto-2.0 \|\| { ... exit 1; }` | **Medium** — primary git pull; fixes prod blocker |
| `.github/workflows/deploy_session_manager.yml` | 146 | Same as 88 | Same replacement | **Medium** — docker rebuild step |
| `.github/workflows/deploy.yml` | 19–21 | Comments: `cd /home/ubuntu/automated-trading-platform` | `cd /home/ubuntu/crypto-2.0` | **None** — comments only |
| `.github/workflows/deploy.yml` | 166–168 | `mkdir -p ~/automated-trading-platform` … | `~/crypto-2.0` | **High** — creates wrong dir if canonical exists elsewhere |
| `.github/workflows/deploy.yml` | 176, 201, 214, 222 | `cd ~/automated-trading-platform` | `cd ~/crypto-2.0` | **High** — SSH deploy path |
| `.github/workflows/deploy.yml` | 194 | rsync to `~/automated-trading-platform/` | `~/crypto-2.0/` | **High** — sync target |

---

## Tier 2 — Primary deploy scripts (patched in minimal diff)

| File | Line | Current | Proposed | Risk |
|------|------|---------|----------|------|
| `deploy_all.sh` | 51 | legacy `cd` (PAT inject) | `crypto-2.0` | Low |
| `deploy_all.sh` | 73, 100 | legacy `cd` fatal | `crypto-2.0` | Medium |
| `deploy_github_token_ssm.sh` | 9 | `PROJECT_DIR="automated-trading-platform"` | `PROJECT_DIR="crypto-2.0"` | Medium |
| `scripts/aws/push_runtime_env_to_ec2.sh` | 58–59 | `/home/ubuntu/automated-trading-platform/...` | `/home/ubuntu/crypto-2.0/...` | **High** — wrong secrets file if unpatched |
| `scripts/deploy_production.sh` | 24 | `REMOTE_PROJECT_DIR` default legacy | `/home/ubuntu/crypto-2.0` | Medium |
| `scripts/aws/deploy_all_manual_commands.sh` | 14 | legacy-only `cd` | `crypto-2.0` | Medium |
| `scripts/aws/inject_aws_creds_to_prod.sh` | 32, 60 | legacy-only `cd` | `crypto-2.0` | Medium |
| `deploy_aws.sh` | 33 | `REMOTE_DIR` default legacy | `/home/ubuntu/crypto-2.0` | Medium |
| `deploy_aws.sh` | 161, 180 | SSH heredoc `cd` legacy | `crypto-2.0` | Medium |
| `restart_backend_ssm.sh` | 26 | `cd ~/automated-trading-platform` | `cd ~/crypto-2.0` | Low |
| `scripts/verify_deploy_secrets.sh` | 9 | comment `~/automated-trading-platform` | `~/crypto-2.0` | None |
| `secrets/runtime.env.example` | 112 | `ATP_PROJECT_PATH=/home/ubuntu/automated-trading-platform` | `/home/ubuntu/crypto-2.0` | Low |
| `backend/app/services/atp_ssm_runner.py` | 9, 24 | legacy path | `crypto-2.0` | **High** — agent SSM commands run in wrong cwd |

---

## Tier 3 — Runtime / admin (recommended; not in minimal diff)

| File | Line(s) | Current | Proposed | Risk if unpatched |
|------|---------|---------|----------|-------------------|
| `backend/app/services/lab_ssm_runner.py` | 9, 24 | legacy | `crypto-2.0` or LAB-specific | LAB agent commands wrong cwd |
| `backend/app/api/routes_admin.py` | 95, 102 | legacy in embedded script | `crypto-2.0` | Admin diagnostics wrong path |
| `scripts/ssm/run_atp_checks.sh` | 11–12 | returns legacy if exists | prefer `crypto-2.0` only | Low — already prefers crypto |

---

## Tier 4 — SSM deploy / fix scripts (legacy-only; not in minimal diff)

One-off `deploy_*.sh` at repo root (~40 files) and `scripts/aws/*_ssm.sh` helpers. Full line listing available via:

```bash
rg -n '/home/ubuntu/automated-trading-platform|~/automated-trading-platform' \
  --glob '*.sh' --glob '*.yml' --glob '*.py' \
  /home/ubuntu/crypto-2.0 \
  --glob '!docs/**'
```

**Bulk replacement command (operator review before running):**

```bash
cd /home/ubuntu/crypto-2.0
rg -l '/home/ubuntu/automated-trading-platform' --glob '*.sh' --glob '*.yml' --glob '*.py' \
  --glob '!docs/**' | while read -r f; do
  sed -i 's|/home/ubuntu/automated-trading-platform|/home/ubuntu/crypto-2.0|g' "$f"
  sed -i 's|~/automated-trading-platform|~/crypto-2.0|g' "$f"
done
```

---

## Tier 5 — systemd units (not in minimal diff)

| File | Lines | Risk |
|------|-------|------|
| `scripts/selfheal/systemd/atp-selfheal.service` | 9–10 | Self-heal timer fails |
| `scripts/selfheal/systemd/atp-health-snapshot.service` | 7–8 | Health snapshot fails |
| `scripts/selfheal/systemd/atp-health-alert.service` | 7–8 | Alert script fails |
| `scripts/health_monitor.service` | 9–14 | Monitor service fails |
| `scripts/dashboard_health_check.service` | 8–13 | Dashboard check fails |
| `scripts/aws/systemd/nightly-integrity-audit.service` | 9–11 | Nightly audit fails |

**Operator action after code patch:** `sudo systemctl daemon-reload` on EC2 if units already installed.

---

## Tier 6 — OpenClaw / LAB scripts (out of PROD deploy scope)

`scripts/openclaw/*` (~25 files) default `ATP_REPO_PATH` to legacy. LAB may still use legacy layout; patch separately or use `ATP_REPO_PATH` env override.

---

## Minimal patch scope applied

The following files were updated in the working tree (not committed):

1. `.github/workflows/deploy_session_manager.yml`
2. `.github/workflows/deploy.yml`
3. `deploy_all.sh`
4. `deploy_github_token_ssm.sh`
5. `scripts/aws/push_runtime_env_to_ec2.sh`
6. `scripts/deploy_production.sh`
7. `scripts/aws/deploy_all_manual_commands.sh`
8. `scripts/aws/inject_aws_creds_to_prod.sh`
9. `deploy_aws.sh`
10. `restart_backend_ssm.sh`
11. `scripts/verify_deploy_secrets.sh`
12. `secrets/runtime.env.example`
13. `backend/app/services/atp_ssm_runner.py`

---

## Post-patch verification (EC2)

```bash
cd /home/ubuntu/crypto-2.0
git diff --stat
grep -r 'automated-trading-platform' .github/workflows/deploy_session_manager.yml deploy_all.sh || echo "Tier-1 clean"
docker compose --profile aws ps
./scripts/verify_deploy_secrets.sh
```

---

## Risk summary

| Change | Risk level | Mitigation |
|--------|------------|------------|
| `deploy_session_manager.yml` path fix | **Low–Medium** | Test via `workflow_dispatch` before relying on push-to-main |
| `atp_ssm_runner.py` cwd | **Medium** | Smoke `run-atp-command` after deploy |
| `push_runtime_env_to_ec2.sh` | **Medium** | Confirm `secrets/runtime.env` lands under active compose root |
| Bulk one-off `deploy_*.sh` left unchanged | **Low** | Legacy scripts rarely used; document as Tier 4 |
| systemd units unchanged | **Medium** | Re-install units on EC2 when path changes |
