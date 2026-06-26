# Remaining Legacy References — `automated-trading-platform`

**Date:** 2026-06-09  
**Post path commit:** `cb175c2`  
**Search scope:** Filesystem paths (`/home/ubuntu/automated-trading-platform`, `~/automated-trading-platform`)

**Excluded from this inventory (intentional, not filesystem paths):**
- SSM parameter prefixes: `/automated-trading-platform/prod/...`
- Docker container name filters: `automated-trading-platform-backend`
- Mac developer paths: `/Users/carloscruz/automated-trading-platform`

---

## Summary by tier

| Tier | Description | Count (approx.) | Action |
|------|-------------|-----------------|--------|
| **Tier 1** | Production critical — **FIXED in cb175c2** | 0 remaining | None |
| **Tier 2** | Deploy / ops scripts not in Tier-1 commit | ~15 | Follow-up PR |
| **Tier 3** | Diagnostics / verification | ~25 | Lower priority |
| **Tier 4** | Documentation | ~40+ files | Update when convenient |
| **Tier 5** | OpenClaw / LAB only | ~12 | LAB-specific; defer or LAB path PR |

---

## Tier 1 — Production critical (FIXED)

All Tier-1 deploy entry points patched in `cb175c2`:

| File | Status |
|------|--------|
| `.github/workflows/deploy_session_manager.yml` | **Fixed** |
| `.github/workflows/deploy.yml` | **Fixed** |
| `deploy_all.sh` | **Fixed** |
| `deploy_aws.sh` | **Fixed** |
| `deploy_github_token_ssm.sh` | **Fixed** |
| `restart_backend_ssm.sh` | **Fixed** |
| `scripts/aws/push_runtime_env_to_ec2.sh` | **Fixed** |
| `scripts/aws/inject_aws_creds_to_prod.sh` | **Fixed** |
| `scripts/deploy_production.sh` | **Fixed** |
| `backend/app/services/atp_ssm_runner.py` | **Fixed** |

---

## Tier 2 — Deploy / ops scripts (remaining)

| File | Line(s) | Risk | Action required |
|------|---------|------|-----------------|
| `update_telegram_menu_aws_ssm.sh` | 24, 26 | **High** — legacy-only `cd`, exits on crypto-2.0-only PROD | Change to `crypto-2.0` |
| `update_coins_aws_ssm.sh` | 102 | **High** — legacy-only `cd` | Change to `crypto-2.0` |
| `verify_deployment.sh` | 11 | Medium — legacy-only SSM | Change to `crypto-2.0` |
| `verify_code_in_container.sh` | 12 | Medium — legacy-only | Change to `crypto-2.0` |
| `verify_monitor_active_alerts.sh` | 28 | Medium — legacy-first | Prefer `crypto-2.0` |
| `reset_telegram_updates.sh` | 18, 36–37, 54, 71 | Medium — legacy-only | Change to `crypto-2.0` |
| `run_audit_via_ssm.sh` | 25 | Medium | Change to `crypto-2.0` |
| `test_telegram_auth.sh` | 13 | Medium | Change to `crypto-2.0` |
| `verificar_despliegue.sh` | 15 | Low | Update path |
| `verificar_deploy.sh` | 78, 83, 92, 96 | Low | Update SSH examples |
| `scripts/deploy_production_via_ssm.sh` | 65 | Low — has fallback | Prefer crypto-2.0 first |
| `deploy_via_ssm.sh` | 46, 58 | Low — has fallback | Prefer crypto-2.0 first |
| `deploy_telegram_reliability_fix.sh` | 25 | Low — has fallback | OK with fallback |
| `scripts/aws/fix_runtime_env_and_up_ssm.sh` | 25 | Low — has fallback | OK |
| `backend/app/api/routes_admin.py` | 95, 102 | Medium — admin embedded script | Update to `crypto-2.0` |

---

## Tier 3 — Diagnostics (remaining)

| File | Line(s) | Risk | Action required |
|------|---------|------|-----------------|
| `scripts/verify_ec2_ip_and_health.sh` | 27 | Low — legacy-first | Prefer crypto-2.0 |
| `scripts/diag/run_get_channel_id_prod.sh` | 11 | Low — default env | Update default |
| `scripts/diag/run_telegram_diagnostic_prod.sh` | 12 | Low | Update default |
| `scripts/diag/validate_atp_runtime_context_prod_via_ssm.sh` | 12, 35 | Low — has fallback | Prefer crypto-2.0 |
| `scripts/aws/update_telegram_chat_id.sh` | 21 | Low | Update default |
| `scripts/aws/update_telegram_chat_id_ops.sh` | 17 | Low | Update default |
| `scripts/aws/update_atp_control_chat_id.sh` | 15 | Low | Update default |
| `scripts/aws/verify_telegram_task_production.sh` | 14 | Low — default arg | Update default |
| `scripts/verify_telegram_config_aws.sh` | 14 | Low — has fallback | OK |
| `scripts/fix_telegram_anomalies_via_ssm.sh` | 42 | Low — has fallback | OK |
| `scripts/run_order_history_deploy_and_capture.sh` | 6 | Low — fallback | OK |
| `scripts/ssm/run_atp_checks.sh` | 11–12 | Low — prefers crypto-2.0 | OK (already canonical-first) |
| `scripts/ec2_add_exchange_credentials.sh` | 5, 8 | Low | Update default |
| `scripts/selfheal/remediate_market_data.sh` | 7 | Low — comment only | Update comment |
| `scripts/write_verify_ec2_ip_and_health.py` | 37 | Low | Prefer crypto-2.0 |
| `verify_swing_conservative_deployment.sh` | 112 | Low | Prefer crypto-2.0 |
| `scripts/aws/forensic_telegram_task_runtime.sh` | 13 | Low — default | Update default |
| `scripts/aws/run_forensic_telegram_task_via_ssm.sh` | 23 | Low — has fallback | OK |
| `scripts/run_notion_task_pickup_via_ssm.sh` | 41, 80 | Low | Update |
| `scripts/aws/prod_free_disk_via_ssm.sh` | 46 | Low — has fallback | OK |

---

## Tier 4 — Documentation (remaining)

Representative files (not exhaustive):

| File | Risk | Action |
|------|------|--------|
| `docs/contracts/deployment_aws.md` | Low — stale | Update to crypto-2.0 |
| `docs/DEPLOYMENT_COMMANDS.md` | Low | Update SSH examples |
| `docs/runbooks/MANUAL_REDEPLOY_EC2.md` | Low | Update |
| `docs/runbooks/PROD_SWAP_DEPLOYMENT_RUNBOOK.md` | Low | Update |
| `docs/runbooks/EC2_SELFHEAL_DEPLOY.md` | Low | Update |
| `docs/cursor-deployment-reference.md` | Low | Update |
| `docs/TELEGRAM_AWS_RUNBOOK.md` | Low | Update |
| `docs/WORKFLOW_DEVOPS_DEPLOYMENT.md` | Low | Update |
| `docs/aws/COMANDOS_PARA_EJECUTAR.md` | Low | Update |
| `docs/audits/*.md` (pre-path) | None — historical | Refresh or archive |

**Action:** Documentation sweep in separate low-risk PR.

---

## Tier 5 — OpenClaw / LAB only

| File | Line(s) | Risk | Action required |
|------|---------|------|-----------------|
| `backend/app/services/lab_ssm_runner.py` | 9, 24 | Medium — LAB agent cwd | LAB path PR or env override |
| `scripts/openclaw/lab_bootstrap_ssm.sh` | 6 | Low — LAB | LAB-specific |
| `scripts/openclaw/deploy_openclaw_lab_from_mac.sh` | 23 | Low | LAB default |
| `scripts/openclaw/build_on_lab_and_restart.sh` | 20 | Low | LAB default |
| `scripts/openclaw/repair_openclaw_lab_on_instance.sh` | 5, 39, 199 | Low | LAB instance |
| `scripts/openclaw/setup_openclaw_token.sh` | 8 | Low — comment | Update comment |
| `scripts/aws/lab_notion_oneliner_ssm.sh` | 14, 16 | Low — LAB | LAB path |
| `scripts/aws/deploy_notion_runtime_to_lab_and_verify.sh` | 42–43, 64, 85, 107 | Low — LAB | LAB path |
| `scripts/aws/store_lab_notion_api_key_ssm.sh` | 40 | Low — echo | Update example |

**Action:** Defer to LAB migration or keep if LAB instance still uses legacy path.

---

## Recommended follow-up

1. **Tier 2 PR** — `update_telegram_menu_aws_ssm.sh`, `update_coins_aws_ssm.sh`, `routes_admin.py`
2. **Tier 3 batch** — update `REPO_PATH` defaults to `crypto-2.0`
3. **Tier 4 docs** — align runbooks with canonical path
4. **Tier 5** — separate LAB track
