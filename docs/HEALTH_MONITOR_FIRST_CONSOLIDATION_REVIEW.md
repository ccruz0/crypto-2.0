# Health Monitor First Consolidation Review

**Date:** 2026-03-11  
**Status:** Documentation and review only. No runtime change is being made yet.

---

## 1. Purpose

This document is the **first safe consolidation review target** for the health/recovery stack. It audits everything related to `health_monitor.service` and its scripts/installers so that operators can:

- Confirm what the mechanism does and how it overlaps with the current canonical stack (atp-selfheal, atp-health-snapshot, atp-health-alert).
- Run exact checks on PROD to determine whether `health_monitor` is installed and active.
- Decide later whether to disable it (in favor of atp-selfheal) with a clear rollback path.

**No runtime change is being made in this phase.** No services are disabled, no files removed, no systemd units modified.

**Execution guide:** When ready to perform the first safe consolidation action on PROD (verify then optionally disable `health_monitor.service`), use **[docs/runbooks/PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md](runbooks/PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md)** as the operational runbook.

---

## 2. What health_monitor Appears To Be

From the repository and documentation:

- **Role:** A **continuous monitoring and auto-recovery** loop that runs as a systemd service. It checks Docker services (profile `aws`) every **60 seconds**, detects unhealthy or stopped containers, and attempts recovery (restart, then rebuild if restart fails repeatedly).
- **Behavior:**
  - **Monitor:** Uses `docker compose --profile aws ps` and service health/state to determine healthy vs unhealthy vs not running.
  - **Remediate:** Restarts services via `docker compose --profile aws restart` (or stop/start); after 3 failed restart attempts, runs rebuild via `docker compose --profile aws build` and `up -d`. Also checks DB (`pg_isready`) and Nginx (via SSH to a hardcoded host) and restarts them if needed.
  - **Logging:** Writes to `logs/health_monitor.log` and `logs/health_monitor.error.log` under the project directory; no Telegram or external alerting in this script.
- **Schedule:** Runs as a **long-lived process** (infinite `while true` loop with 60s sleep), not a timer. Started by systemd and kept running with `Restart=always`.
- **Installation:** Via `install_health_monitor.sh`, which SCPs the script and service file to a remote host and enables/starts `health_monitor.service`. The installer uses a **hardcoded default host** `ubuntu@175.41.189.249` (legacy IP), so it may never have been run against current PROD.

---

## 3. Files and Components Involved

| Item | Path / location | Notes |
|------|------------------|--------|
| **Script** | `scripts/health_monitor.sh` | Main loop: check services, restart, rebuild, check DB/Nginx. |
| **Systemd unit** | `scripts/health_monitor.service` | Unit file; installed to `/etc/systemd/system/health_monitor.service` by installer. |
| **Installer** | `install_health_monitor.sh` | Copies script + service to host, `systemctl enable` + `start`. Default `HOST=ubuntu@175.41.189.249`. |
| **README** | `README_HEALTH_MONITOR.md` | Spanish-language description, installation, troubleshooting. |
| **Docs (references)** | `docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md`, `docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md`, `docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md` | Overlap and consolidation context. |
| **Docs (monitoring)** | `docs/AWS_HEALTH_MONITORING_SUMMARY.md`, `docs/AWS_HEALTH_MONITORING_TOOLS.md`, `docs/AWS_SYSTEM_STATUS_REVIEW_CURRENT.md`, `docs/monitoring.md`, `docs/project-overview.md` | Describe or reference health_monitor. |
| **Docs (other)** | `docs/monitoring/HEALTH_MONITORING.md`, `docs/VERSION_4.0_TECHNICAL_DESCRIPTION.md`, `docs/audits/AUDIT_AWS.md`, `AUDIT_AWS.md`, `CHANGELOG.md` | Mention health_monitor or install. |
| **Script (stack start)** | `scripts/start-stack-and-health.sh` | Can call `install_health_monitor.sh` with a SERVER variable. |
| **Log paths (on host)** | `$PROJECT_DIR/logs/health_monitor.log`, `$PROJECT_DIR/logs/health_monitor.error.log` | Where the script writes when run on server. |
| **State file (script)** | `$PROJECT_DIR/.restart_counts` | Per-service restart attempt counts. |

There is **no** separate systemd *timer* for health_monitor; it is a single **service** that runs continuously.

---

## 4. Overlap With Current Canonical Mechanisms

| Canonical mechanism | Overlap with health_monitor | Type (monitor / alert / remediate) | Confirmed or suspected |
|--------------------|-----------------------------|-------------------------------------|-------------------------|
| **atp-selfheal.timer** | Both restart Docker stack and can restart/reload nginx. atp-selfheal runs verify.sh → heal.sh every 2 min (disk cleanup, compose up, POST /api/health/fix, nginx reload). health_monitor runs a 60s loop with compose restart/rebuild and nginx restart via SSH. | **Remediate** (both). | **Suspected** — same host would have two independent restart paths; overlap is logical, not yet confirmed on PROD. |
| **atp-health-snapshot.timer** | Snapshot writes verify.sh + /api/health/system to log; no restart. health_monitor does not write that log. Different role (snapshot = record; health_monitor = act). | Monitor (snapshot) vs remediate (health_monitor). | **No direct overlap** — complementary. |
| **atp-health-alert.timer** | Alert reads snapshot log, sends Telegram, runs remediate_market_data.sh. health_monitor has no Telegram and no snapshot log. | Alert vs remediate (different scope). | **No direct overlap** — different signals and actions. |
| **Backend health endpoints** | verify.sh (used by atp-selfheal and snapshot) calls /api/health and /api/health/system. health_monitor does not call these; it uses only docker compose ps and pg_isready. | Backend used by canonical stack; health_monitor uses Docker/DB only. | **No overlap** — health_monitor does not use backend health API. |
| **Telegram health signaling** | atp-health-alert sends Telegram on streak-fail. health_monitor has no Telegram. | Alert only in atp-health-alert. | **No overlap** — health_monitor does not signal Telegram. |

**Summary:** The only **real overlap** is with **atp-selfheal.timer**: both can **remediate** (restart Docker services and nginx). If both run on PROD, they can double-restart, race with locks (e.g. atp-selfheal’s flock), or mask which mechanism is actually recovering the system. Overlap is **suspected** until PROD is checked and confirms that `health_monitor.service` is present and active.

---

## 5. Runtime Risk If Left In Place

If `health_monitor.service` is **active** on PROD alongside the current timer-based stack:

- **Double remediation:** Same unhealthy container could be restarted by health_monitor (every 60s) and by atp-selfheal (every 2 min via heal.sh), leading to redundant restarts and possible flapping.
- **Lock/ordering:** atp-selfheal uses a lock (`/var/lock/atp-selfheal.lock`) and ordered steps (verify → heal). health_monitor has no knowledge of that lock and can run compose restart/rebuild in parallel, which can conflict or make debugging harder.
- **Nginx:** Both can restart nginx (heal.sh and health_monitor’s `restart_nginx`). Duplicate restarts are mostly harmless but add noise and duplicate actions.
- **Resource and log noise:** Two loops doing similar checks and restarts increase log volume and make it harder to attribute recovery to one mechanism.

---

## 6. Runtime Risk If Disabled Blindly

Disabling `health_monitor.service` **without verification** is not recommended because:

- **Might be the only remediation on an older host:** If PROD (or another host) was set up before atp-selfheal was deployed, health_monitor might be the only automatic recovery. Disabling it without confirming that atp-selfheal is installed and working could remove all auto-recovery on that host.
- **Might not be present:** The installer uses an old hardcoded IP; health_monitor might never have been installed on current PROD. In that case there is nothing to disable, and the “consolidation” is to document “not present.”
- **Correct sequence:** First confirm on PROD whether the unit exists and is enabled/active; then, if it is active and atp-selfheal is also active, plan a single disable of health_monitor with verification and rollback.

---

## 7. Exact Checks To Perform On PROD Before Any Change

Run these on the PROD instance (e.g. via SSM or SSH). They verify whether `health_monitor` exists and is active; no changes are made.

```bash
# 1. Service status and enabled/active state
sudo systemctl status health_monitor.service --no-pager -l
sudo systemctl is-enabled health_monitor.service
sudo systemctl is-active health_monitor.service

# 2. Recent journal output (if unit exists)
sudo journalctl -u health_monitor.service -n 200 --no-pager

# 3. Unit file presence
ls -la /etc/systemd/system/health_monitor.service 2>/dev/null || echo "Unit file not found"
systemctl list-unit-files --no-pager | grep -iE 'health_monitor|health-monitor'

# 4. Search for any unit or script named health_monitor / health-monitor under system paths and home
sudo find /etc/systemd /usr/local/bin /opt /home /root -type f 2>/dev/null | grep -Ei 'health_monitor|health-monitor'

# 5. Grep for references in config and home (may need to trim output on a busy system)
sudo grep -RinE 'health_monitor|health-monitor' /etc/systemd /opt /home /root 2>/dev/null | head -200
```

**Optional (confirm canonical stack is healthy before considering disable):**

```bash
# Confirm atp-selfheal is the remediation path we keep
sudo systemctl status atp-selfheal.timer --no-pager
sudo systemctl is-active atp-selfheal.timer
sudo journalctl -u atp-selfheal.service -n 30 --no-pager
```

Document the results: (a) unit present or not, (b) enabled/active or not, (c) any other health_monitor/health-monitor files found. If the unit is not present, document “health_monitor not installed on PROD” and no host change is required.

---

## 8. Safest Possible Change If It Is Confirmed Active

**Only after** the checks in §7 confirm that `health_monitor.service` is **installed and active** on PROD, and that atp-selfheal is also active and healthy, the minimal future action would be:

1. **Disable and stop** `health_monitor.service` only:
   - `sudo systemctl stop health_monitor.service`
   - `sudo systemctl disable health_monitor.service`
2. **Do not delete** any files (repo or under `/etc/systemd`) in this step. The unit and script can remain so that re-enable is trivial.
3. **Verify** that ATP timers and stack remain healthy:
   - `sudo systemctl status atp-selfheal.timer atp-health-snapshot.timer atp-health-alert.timer --no-pager`
   - `sudo journalctl -u atp-selfheal.service -n 20 --no-pager`
   - Local GET /api/health (and optionally /api/health/system).
4. **Observe** for 24–48 hours: no regression in recovery behavior, no new unrecovered failures.
5. **Keep rollback simple:** Re-enable with the commands in §9 if needed.

No other mechanisms (atp-health-snapshot, atp-health-alert, cron, dashboard_health_check) should be changed in this first consolidation step.

---

## 9. Rollback Plan

If after disabling `health_monitor.service` we need to re-enable it:

```bash
sudo systemctl enable health_monitor.service
sudo systemctl start health_monitor.service
sudo systemctl status health_monitor.service --no-pager
```

If the unit file was removed from the host (not recommended in the first step), re-install by running `install_health_monitor.sh` with the correct `HOST` for PROD (e.g. `HOST=ubuntu@<PROD_IP>` or via SSM copy + systemctl enable/start).

---

## 10. Recommendation

Based on repo evidence:

- **health_monitor.service remains the safest first consolidation candidate.**  
- It is the clearest **remediation** duplicate of **atp-selfheal.timer** (both restart Docker and nginx), with no Telegram or snapshot role.
- The installer’s hardcoded IP suggests it may **not** be installed on current PROD; the first step is still to run the §7 checks and document presence/absence.
- **Do not disable anything until** PROD checks are done and (if active) the minimal change in §8 is approved with rollback and verification steps in place.

---

**Related:**  
- **docs/runbooks/PROD_HEALTH_MONITOR_FIRST_CONSOLIDATION_RUNBOOK.md** — Operational runbook for the first safe consolidation action (verify → disable if active → verify).  
- **docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md** — Overall strategy and first target.  
- **docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md** — Repo audit.  
- **docs/ATP_RUNTIME_HEALTH_RECOVERY_BASELINE.md** — LAB/PROD runtime inventory.
