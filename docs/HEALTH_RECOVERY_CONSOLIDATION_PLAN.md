# Health/Recovery Consolidation Plan

**Date:** 2026-03-11  
**Status:** Planning and analysis only. No implementation, removal, or disabling of mechanisms.

---

## 1. Purpose

The goal of this plan is to **reduce overlap and confusion** among health and recovery mechanisms without removing protections blindly. Multiple systems exist in the repo and on PROD (self-heal, health snapshot, health alert, legacy monitors). Consolidation should:

- Clarify which mechanisms are canonical and which are legacy or duplicate.
- Reduce the risk of double-restarts, conflicting alerts, or competing remediation.
- Preserve all proven recovery and alerting behavior until replacement is intentional and verified.

This document is **planning and consolidation strategy only**. It does not authorize any immediate changes to timers, scripts, or services.

---

## 2. Current Confirmed Mechanisms

### Active on PROD (confirmed post-recovery 2026-03-11)

| Mechanism | Type | Interval | Purpose |
|-----------|------|----------|---------|
| **atp-selfheal.timer** | systemd timer | 2 min | Runs verify.sh → heal.sh: disk cleanup, stack restart, POST /api/health/fix, nginx reload. |
| **atp-health-snapshot.timer** | systemd timer | 5 min | Runs health_snapshot_log.sh: verify.sh + GET /api/health/system → `/var/log/atp/health_snapshots.log`. |
| **atp-health-alert.timer** | systemd timer | 5 min | Runs health_snapshot_telegram_alert.sh: streak-fail rule, remediate_market_data.sh, Telegram alerts with dedupe. |
| **Docker** | service + compose | — | restart policies + healthchecks (backend, db, market-updater-aws, etc.). |
| **Backend health API** | app | — | /api/health, /api/health/system, POST /api/health/fix, POST /api/health/repair. |
| **nginx** | service | — | Reverse proxy; required for external /api/health. |
| **SSM agent (snap)** | service | — | Remote management; unit: snap.amazon-ssm-agent.amazon-ssm-agent.service. |

### Repo-level candidates that may overlap (not all confirmed on PROD)

| Candidate | Location | Purpose | Confirmed on PROD? |
|-----------|----------|---------|---------------------|
| **health_monitor.service** | scripts/health_monitor.sh, install_health_monitor.sh | 60s loop: restart/rebuild Docker + DB + Nginx | **Unconfirmed** — install script uses old IP; may not be deployed. |
| **infra/monitor_health.py** (cron) | infra/install_health_cron.sh | 5 min cron: container + HTTP checks, Telegram, optional restarts | **Unconfirmed** — unclear if cron is installed on PROD. |
| **dashboard_health_check** | scripts/dashboard_health_check.sh, systemd timer | 20 min: check /api/market/top-coins-data, Telegram on failure | **Unconfirmed** — timer not confirmed in baseline. |
| **nightly-integrity-audit.timer** | scripts/aws/nightly_integrity_audit.sh | 03:15 local: stack + health_guard + portfolio, Telegram on first failure | **Unconfirmed** — not in confirmed PROD list. |
| **GitHub Actions prod-health-check** | .github/workflows/prod-health-check.yml | 6h + on push: curl PROD /api/health | Active (CI); no overlap with host-side recovery. |

---

## 3. Consolidation Risks

Consolidating too aggressively can:

- **Break recovery:** Disabling or removing a mechanism that is still the only one performing a given remediation (e.g. disk cleanup, market-data restart) can leave PROD without that protection.
- **Lose signal coverage:** Merging or removing alert paths without ensuring the remaining path covers the same failure modes (e.g. streak-fail, incident dedupe) can reduce visibility.
- **Duplicate alert flows:** Enabling a second Telegram path without disabling the first leads to duplicate or conflicting notifications.
- **Conflicting restart behavior:** Two mechanisms restarting the same services (e.g. health_monitor + atp-selfheal) can double-restart, race with locks, or mask the root cause.
- **Removing mechanisms still needed:** Legacy or “redundant” scripts might still be in use on a specific host or for a specific scenario; removing them without confirming runtime state can break that scenario.

Therefore: **consolidation must be incremental, one candidate at a time, with verification after each change.**

---

## 4. Candidate Overlaps

For each candidate overlap, we state what overlaps, current confidence, and what is confirmed vs unconfirmed.

### 4.1 atp-selfheal vs older health monitor scripts

- **What overlaps:** Both can restart Docker/stack and nginx. health_monitor.sh runs a 60s loop with restart/rebuild; atp-selfheal runs verify.sh → heal.sh every 2 min (disk + compose up + health/fix + nginx reload).
- **Current confidence:** High that they duplicate *if both run*. Low confidence that health_monitor is actually installed on current PROD (install script has hardcoded old IP).
- **Confirmed:** atp-selfheal.timer is active on PROD.  
- **Unconfirmed:** Whether health_monitor.service is installed or enabled on PROD.

### 4.2 Health snapshot vs health alert flows

- **What overlaps:** atp-health-snapshot writes the log; atp-health-alert reads it and sends Telegram + runs remediate_market_data.sh. They are designed to work together (snapshot → alert), not as duplicates. Overlap is in “who decides unhealthy” (both use verify.sh / health_snapshot_log.sh output).
- **Current confidence:** These are a single logical “health snapshot + alert” stack; no consolidation between them—keep both.
- **Confirmed:** Both timers active on PROD.  
- **Unconfirmed:** N/A for consolidation (no merge intended).

### 4.3 Repo-level legacy scripts vs active PROD timers

- **What overlaps:** install_health_monitor.sh, install_health_cron.sh (monitor_health.py), install_dashboard_health_check.sh deploy alternate health/alert paths that can run alongside atp-selfheal and atp-health-alert.
- **Current confidence:** Medium—repo contains multiple install paths; runtime presence on PROD is not fully documented for cron/dashboard_health_check/nightly-integrity.
- **Confirmed:** atp-selfheal, atp-health-snapshot, atp-health-alert are confirmed on PROD.  
- **Unconfirmed:** Which (if any) of health_monitor, cron monitor_health.py, dashboard_health_check, nightly-integrity are installed and enabled on PROD.

### 4.4 Duplicate Telegram-style health signaling paths

- **What overlaps:** atp-health-alert (streak-fail + dedupe), dashboard_health_check (top-coins-data failure → Telegram), infra/monitor_health.py (cron → Telegram), nightly_integrity_audit (first failure → Telegram). Multiple paths can send Telegram for different or similar conditions.
- **Current confidence:** High overlap in “send Telegram on some failure”; low confidence on which of dashboard_health_check / monitor_health.py / nightly are actually running on PROD.
- **Confirmed:** atp-health-alert is the canonical health-failure alert path on PROD.  
- **Unconfirmed:** Whether any other Telegram-sending timer or cron is active on PROD.

---

## 5. What Must Be Preserved

The following must **not** be disrupted by consolidation planning or future implementation:

- **EC2 host recovery:** Existing EC2 auto-recovery preparation and swap configuration; no change to AWS recovery behavior unless explicitly planned elsewhere.
- **Existing proven PROD timers** (atp-selfheal, atp-health-snapshot, atp-health-alert) until replacement is intentional, documented, and verified in a maintenance window.
- **nginx/docker/backend runtime stability:** No change to docker-compose, nginx config, or backend trading logic as part of this consolidation.
- **SSM access:** No change that would remove or weaken SSM agent or snap unit configuration.
- **Current external /api/health behavior:** GET /api/health and GET /api/health/system must remain the canonical external and internal health endpoints; no removal or breaking change to these routes.

---

## 6. Safest Consolidation Strategy

Recommended order of operations:

1. **Document active mechanisms:** On each relevant host (at least PROD), run the runtime checks from docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md and docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md (e.g. `systemctl list-timers`, status of atp-*, health_monitor, dashboard_health_check, nightly-integrity; crontab -l; root crontab). Produce a one-page “current health/recovery stack” (what runs where, at what interval).
2. **Identify inactive/legacy ones:** From that document, mark which mechanisms are installed but disabled, or not installed at all. Do not assume “not in repo” means “not on host.”
3. **Disable only one duplicate candidate at a time:** If a duplicate is confirmed (e.g. health_monitor.service and atp-selfheal.timer both running), disable only one (prefer keeping atp-selfheal), then verify.
4. **Verify stability after each change:** After any disable or change, confirm: atp-selfheal still runs and logs PASS/HEALED as expected; health snapshot log still updated; health alert still fires on test; no duplicate restarts; SSM and /api/health still healthy.
5. **Keep rollback simple:** Document the exact enable/disable commands (e.g. `systemctl stop/disable <unit>`) so the change can be reverted in one step.

No step in this strategy is “remove from repo” or “delete scripts” until long after a mechanism is confirmed disabled everywhere and superseded.

---

## 7. Immediate No-Change Candidates

The following should **definitely remain untouched for now**:

- **atp-selfheal.timer / atp-selfheal.service** — Primary host-level remediation on PROD.
- **atp-health-snapshot.timer / atp-health-snapshot.service** — Feeds the health timeline and the alert pipeline.
- **atp-health-alert.timer / atp-health-alert.service** — Canonical Telegram health-failure path with dedupe and remediation.
- **Docker restart policies and healthchecks** — Container-level recovery.
- **Backend /api/health, /api/health/system, POST /api/health/fix, POST /api/health/repair** — Used by verify.sh, heal.sh, and health snapshot/alert.
- **scripts/selfheal/verify.sh, heal.sh, run.sh** — Core of self-heal and snapshot.
- **scripts/diag/health_snapshot_log.sh, health_snapshot_telegram_alert.sh** — Snapshot and alert pipeline.
- **scripts/selfheal/remediate_market_data.sh** — Targeted market-data remediation invoked by health-alert.
- **EC2 auto-recovery and swap** — Host-level safety; out of scope for this consolidation.
- **GitHub Actions prod-health-check** — External probe; does not duplicate host-side recovery.

---

## 8. Candidates For Future Review

These deserve review later but **should not yet be removed or disabled** until runtime state is confirmed and a consolidation step is planned:

- **health_monitor.service / scripts/health_monitor.sh** — If ever confirmed running on PROD alongside atp-selfheal, consider disabling health_monitor and keeping atp-selfheal as the single remediation path.
- **infra/monitor_health.py + install_health_cron.sh** — If cron is confirmed on PROD and overlaps with atp-health-alert, consider removing the cron job and keeping atp-health-alert as the single health-failure Telegram path.
- **dashboard_health_check (script + timer)** — If installed and sending Telegram, consider whether its signal is redundant with atp-health-alert or serves a distinct check (e.g. top-coins-data); then either repurpose or disable in favor of one canonical alert path.
- **nightly-integrity-audit.timer** — If installed, it is a different schedule (once daily) and different checks; document whether it is active on PROD and whether its Telegram path should be merged or kept separate.
- **scripts/aws/health_guard.sh** — Used in verification/nightly scripts; not a standalone watchdog. Keep as a helper; no consolidation needed unless usage changes.

---

## 9. Suggested First Consolidation Target

**Recommended single safest future target for consolidation review:**

- **Confirm and, if present, disable `health_monitor.service` on PROD (in favor of atp-selfheal.timer).**
- **Detailed first-review document:** [docs/HEALTH_MONITOR_FIRST_CONSOLIDATION_REVIEW.md](HEALTH_MONITOR_FIRST_CONSOLIDATION_REVIEW.md) — files, overlap analysis, exact PROD checks, and safest change/rollback.

**Rationale:**

- **Lowest risk:** If health_monitor is not installed, the “consolidation” is documentation only (confirm and document “not present”).
- **Highest duplication likelihood:** Both health_monitor and atp-selfheal can restart Docker/stack and nginx; they are the clearest duplicate remediation path identified in the audit.
- **Reversible:** Disabling a systemd service is a one-command rollback (`systemctl enable --now health_monitor.service`).
- **No repo delete:** No removal of scripts or installers; only disable the service on the host after confirming it is running.

**Prerequisite:** Before any disable, run on PROD: `systemctl status health_monitor.service` (and list-timers / list-unit-files) and document the result. If not present, document “health_monitor not installed on PROD” and close the consolidation step with no host change.

---

## 10. Exit Criteria

Consolidation planning is mature enough to begin implementation safely when:

1. **Runtime baseline is documented:** A one-page “current health/recovery stack” exists for PROD (and any other host that runs these mechanisms), listing what is installed, enabled, and running (timers, services, cron).
2. **Inactive/legacy list exists:** From that baseline, every mechanism is classified as: canonical (keep), duplicate (candidate to disable), or unknown (verify first).
3. **First consolidation target is chosen and approved:** The first target (e.g. health_monitor.service) has been confirmed present or absent on PROD, and there is explicit approval to disable only that one candidate.
4. **Rollback steps are written:** For that first target, the exact disable and re-enable commands are documented.
5. **Verification steps are defined:** Post-change checks (e.g. atp-selfheal journal, health snapshot log, /api/health, SSM) are listed and agreed.
6. **No broad removal:** No plan to remove or disable multiple mechanisms in one change; no deletion of repo scripts as part of the first consolidation step.

Until these criteria are met, **do not disable or remove any health/recovery mechanism on PROD.**

---

**Related documents:**

- **docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md** — Repo audit and overlap analysis.
- **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md** — LAB/PROD runtime inventory and canonical stack.
- **docs/PROD_OBSERVABILITY_SIGNALS_PLAN.md** — Observability baseline; next phase is cautious consolidation planning.
- **docs/runbooks/PROD_OBSERVABILITY_CHECKS_RUNBOOK.md** — Manual checks and interpretation.
