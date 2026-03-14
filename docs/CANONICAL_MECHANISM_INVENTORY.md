# Canonical Mechanism Inventory

## 1. Purpose

This document is the **runtime-vs-repo truth source** for health, recovery, observability, and runbook mechanisms in the Automated Trading Platform. It inventories what exists in the repository, what is confirmed on PROD, and how each mechanism is classified (canonical, optional, legacy, not installed, or unknown). Use it to align documentation with runtime reality and to plan consolidation or verification steps without changing runtime behavior.

## 2. Scope

The inventory covers:

- **Health timers** — systemd timers that run health checks, snapshots, or remediation on a schedule
- **Alerting mechanisms** — components that send Telegram or other notifications on failure or anomaly
- **Recovery mechanisms** — components that restart services, Docker, or trigger host-level recovery
- **Observability scripts** — scripts that collect health state, logs, or metrics without performing remediation
- **Runbooks** — documented procedures for operators (deploy, recovery, consolidation, observability)
- **Legacy candidates** — repo mechanisms that may overlap with canonical ones or are not confirmed on PROD

## 3. Inventory Table

| Mechanism | Type | Purpose | Repo Path | Documented | Confirmed On PROD | Active On PROD | Canonical Status | Overlap Risk | Related Runbook | Next Action |
|-----------|------|---------|-----------|------------|-------------------|----------------|------------------|--------------|-----------------|-------------|
| atp-selfheal.timer | systemd timer | Runtime remediation: verify.sh → heal.sh (disk cleanup, stack restart, POST /api/health/fix, nginx reload) | scripts/selfheal/run.sh, verify.sh, heal.sh; scripts/selfheal/systemd/atp-selfheal.{service,timer} | Yes | Yes | Yes | **canonical** | None | EC2_SELFHEAL_DEPLOY.md | Keep; no change |
| atp-health-snapshot.timer | systemd timer | Observation: verify.sh + GET /api/health/system → health_snapshots.log | scripts/diag/health_snapshot_log.sh; scripts/selfheal/systemd/atp-health-snapshot.{service,timer} | Yes | Yes | Yes | **canonical** | None | PROD_OBSERVABILITY_CHECKS_RUNBOOK.md | Keep; no change |
| atp-health-alert.timer | systemd timer | Notification: streak-fail rule, remediate_market_data.sh, Telegram with dedupe | scripts/diag/health_snapshot_telegram_alert.sh; scripts/selfheal/remediate_market_data.sh; scripts/selfheal/systemd/atp-health-alert.{service,timer} | Yes | Yes | Yes | **canonical** | None | PROD_OBSERVABILITY_CHECKS_RUNBOOK.md, ATP_HEALTH_ALERT_STREAK_FAIL.md | Keep; no change |
| Backend health API | app | /api/health, /api/health/system, POST /api/health/fix, POST /api/health/repair | backend (routes) | Yes | Yes | Yes | **canonical** | None | — | Keep; no change |
| Docker + compose | runtime | Container orchestration, restart policies, healthchecks | docker-compose*, Dockerfile* | Yes | Yes | Yes | **canonical** | None | restart-services.md, deploy.md | Keep; no change |
| nginx | service | Reverse proxy; external /api/health | nginx config | Yes | Yes | Yes | **canonical** | None | DASHBOARD_UNREACHABLE_RUNBOOK.md | Keep; no change |
| SSM agent | service | Remote management (snap unit) | — (AWS/snap) | Yes | Yes | Yes | **canonical** | None | — | Keep; no change |
| AWS EC2 recovery | infra | Instance status checks, auto-recovery | infra/aws/ec2_auto_recovery_prod/ | Yes | Prepared | N/A | **canonical** | None | — | No change |
| health_monitor.service | systemd service | 60s loop: restart/rebuild Docker, DB, Nginx (legacy) | scripts/health_monitor.sh, scripts/health_monitor.service, install_health_monitor.sh | Yes | **No** (not installed) | No | **not installed** | High if ever enabled (duplicate of atp-selfheal) | PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md | Document absent; do not install on PROD |
| infra/monitor_health.py (cron) | cron job | 5 min: container + HTTP checks, Telegram, optional restarts | infra/monitor_health.py, infra/install_health_cron.sh | Yes | Unknown | Unknown | **legacy** | Medium (Telegram + possible restart overlap) | — | Verify on PROD: crontab -l; if present, review vs atp-health-alert |
| dashboard_health_check | script + timer | 20 min: /api/market/top-coins-data, Telegram on failure | scripts/dashboard_health_check.sh, install_dashboard_health_check.sh | Yes (e.g. dashboard_healthcheck.md) | Unknown | Unknown | **legacy** | Medium (Telegram overlap) | dashboard_healthcheck.md | Verify on PROD: systemctl list-unit-files; if present, review vs atp-health-alert |
| nightly-integrity-audit.timer | systemd timer | 03:15 local: stack + health_guard + portfolio, Telegram on first failure | scripts/aws/nightly_integrity_audit.sh, scripts/aws/systemd/nightly-integrity-audit.{service,timer}, scripts/aws/_notify_telegram_fail.sh | Yes | Unknown | Unknown | **optional** | Low (different schedule and checks) | EC2_NIGHTLY_INTEGRITY_AUDIT.md, EC2_NIGHTLY_AUDIT_OPERATOR_REPORT.md | Verify on PROD: systemctl status nightly-integrity-audit.timer; document active or not |
| GitHub Actions prod-health-check | workflow | 6h + on push: curl PROD /api/health | .github/workflows/prod-health-check.yml | Yes | Yes (CI) | Yes (CI) | **optional** | None (external probe only) | — | Keep; no host overlap |
| verify.sh | script | Core health check; used by selfheal + snapshot + alert pipeline | scripts/selfheal/verify.sh | Yes | Yes | Yes (via timers) | **canonical** | None | — | No change |
| heal.sh | script | Stack restart, disk cleanup, health/fix, nginx reload | scripts/selfheal/heal.sh | Yes | Yes | Yes (via atp-selfheal) | **canonical** | None | EC2_SELFHEAL_DEPLOY.md | No change |
| remediate_market_data.sh | script | Targeted market-data remediation (invoked by health-alert) | scripts/selfheal/remediate_market_data.sh | Yes | Yes | Yes (via atp-health-alert) | **canonical** | None | EC2_FIX_MARKET_DATA_NOW.md | No change |
| health_guard.sh | script | Helper for integrity/audit scripts; not standalone watchdog | scripts/aws/health_guard.sh | Yes | — | — | **optional** (helper) | None | — | No consolidation needed unless usage changes |

## 4. Confirmed Canonical Mechanisms

The following are **canonical** and confirmed active on PROD (post-recovery 2026-03-11):

- **atp-selfheal.timer** — Single owner of runtime remediation (restart Docker/stack, nginx reload, health/fix).
- **atp-health-snapshot.timer** — Observation only; writes health state to log.
- **atp-health-alert.timer** — Notification only; Telegram with dedupe; may invoke remediate_market_data.sh (targeted, not full stack restart).
- **Backend health API** — /api/health, /api/health/system, POST /api/health/fix, POST /api/health/repair.
- **Docker + compose** — Application runtime.
- **nginx** — Reverse proxy for external /api/health and dashboard.
- **SSM agent** — Remote management.
- **verify.sh, heal.sh, remediate_market_data.sh** — Scripts used by the canonical timers.

AWS EC2 recovery is **canonical** for host-level recovery (prepared; not a timer on the host).

## 5. Confirmed Non-Installed or Non-Active Mechanisms

- **health_monitor.service** — Confirmed **not installed** on PROD. Install script uses legacy hardcoded IP; unit file and script exist in repo but are not deployed on current PROD. Do not install; if ever found enabled elsewhere, disable in favor of atp-selfheal per PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md.

## 6. Legacy / Review Candidates

These may still need verification on PROD and future review (one at a time):

- **infra/monitor_health.py + install_health_cron.sh** — If cron is present on PROD, document and consider whether it duplicates atp-health-alert (Telegram + optional restarts).
- **dashboard_health_check (script + timer)** — If installed, document and assess whether its check (top-coins-data) and Telegram path are redundant with atp-health-alert or distinct.
- **nightly-integrity-audit.timer** — Different schedule (daily) and checks (integrity/portfolio). Verify presence on PROD; if active, document and decide whether to keep as optional or align with canonical alert path.

No removal or disable of these until runtime state is confirmed and a consolidation step is approved with rollback.

## 7. Runbook Alignment Gaps

- **Runbooks that reference unconfirmed mechanisms:** Some runbooks (e.g. EC2_NIGHTLY_INTEGRITY_AUDIT.md, EC2_NIGHTLY_AUDIT_OPERATOR_REPORT.md, dashboard_healthcheck.md) describe nightly-integrity or dashboard_health_check; PROD status for these is still **unknown**. Align by: (1) running verification commands on PROD (systemctl list-unit-files, crontab -l), (2) updating this inventory and the runbooks with “active on PROD” or “not installed on PROD.”
- **Single source of truth:** This inventory (and SOLUTION_ARCHITECTURE_MASTER.md) should be the reference for “what is canonical” and “what is legacy/optional.” Runbooks that describe health/recovery mechanisms should point to this inventory and to CANONICAL_RECOVERY_RESPONSIBILITY_MAP.md for ownership.
- **First consolidation runbook:** PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md is aligned: health_monitor is confirmed not installed; runbook remains the procedure to verify and, if ever found, disable. No runbook change required for health_monitor.

## 8. Recommendation

The **next safest verification target** after health_monitor.service is:

- **Verify on PROD whether `nightly-integrity-audit.timer` and `dashboard_health_check` (timer or cron) are installed and active.**

**Operational verification package:** Use **docs/NEXT_MECHANISM_VERIFICATION_NIGHTLY_DASHBOARD.md** for the exact PROD verification commands, interpretation rules, and inventory update steps. This is **verification and documentation only**; do not disable or remove anything until a dedicated consolidation step is planned for any duplicate.

After that, the next candidate is **infra/monitor_health.py** (cron): verify presence and document overlap with atp-health-alert.
