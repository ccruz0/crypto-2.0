# ATP Existing Health/Recovery Audit

**Date:** 2026-03-11  
**Scope:** Full repository audit for self-healing, watchdog, remediation, health-monitoring, and automatic recovery. No code changes; evidence-based only.

---

## 1. Executive Summary

- **Is there already a health/recovery system?** **Yes (partial)** — Multiple overlapping systems exist; some are active, some are alternate implementations or documentation-only.

- **What appears to be active**
  - **Backend health API**: `/api/health`, `/api/health/system`, `/ping_fast`, `POST /api/health/fix`, `POST /api/health/repair` (x-api-key) — implemented and used.
  - **Self-heal (EC2)**: `scripts/selfheal/` (verify.sh, heal.sh, run.sh) with systemd timer `atp-selfheal.timer` every 2 minutes — documented in EC2_SELFHEAL_DEPLOY.md and README in scripts/selfheal.
  - **Health snapshot + Telegram alert**: `atp-health-snapshot.timer` (every 5 min) → `health_snapshot_log.sh` → `health_snapshot_telegram_alert.sh` with streak-fail rule and targeted remediation (`remediate_market_data.sh`).
  - **Docker**: `restart: always` / `restart: unless-stopped` and healthchecks on backend, db, market-updater-aws, frontend-aws, etc. in docker-compose.yml.
  - **GitHub Actions**: `.github/workflows/prod-health-check.yml` — scheduled every 6h + on push to main; curls PROD `/api/health`.
  - **OpenClaw / agent recovery**: `agent_recovery.py` — autonomous recovery for stuck Notion tasks (orphan smoke check, revalidate patching, etc.); invoked from agent scheduler.

- **What appears to be partial or abandoned**
  - **Health monitor (bash)**: `scripts/health_monitor.sh` + `health_monitor.service` — continuous loop (60s), restart/rebuild Docker services + DB + Nginx. Install via `install_health_monitor.sh` (hardcoded host `175.41.189.249`). Overlaps with selfheal (verify/heal) and may duplicate restarts.
  - **Python health monitor (cron)**: `infra/monitor_health.py` — container + HTTP checks, Telegram alerts, optional restarts; installed via `infra/install_health_cron.sh` (cron every 5 min). Overlaps with both health_monitor.sh and selfheal; unclear if still deployed.
  - **Dashboard health check**: `scripts/dashboard_health_check.sh` — checks `/api/market/top-coins-data`, Telegram on failure; systemd timer every 20 min. Contains redacted token in script; install via `install_dashboard_health_check.sh`.
  - **Health guard**: `scripts/aws/health_guard.sh` — simple curl `/health` (not `/api/health`); used in CI/verification, not a full watchdog.

- **Biggest duplication risks if we build a new system without care**
  1. **Multiple “restart/recover” paths**: health_monitor.sh (restart/rebuild), selfheal heal.sh (disk + stack restart + POST /api/health/fix), health_snapshot_telegram_alert → remediate_market_data.sh (restart market-updater-aws + update-cache ± health/fix). Adding another layer could double-restart or conflict with locks.
  2. **Two “health check + alert” stacks**: (a) atp-health-snapshot + atp-health-alert (verify.sh + log + Telegram with incident dedupe); (b) infra/monitor_health.py (cron) or health_monitor.sh (systemd). A new watchdog could add a third.
  3. **Definition of “healthy”**: Already split between Docker healthcheck (`/api/health` or `ping_fast`), `verify.sh` (disk, containers, api, db, market_data, market_updater, signal_monitor), and `/api/health/system` (global_status + components). Any new system must reuse these or explicitly supersede.

---

## 2. Confirmed Existing Components

### 2.1 Backend system health (single source of truth)

- **Name:** System health computation and API
- **Purpose:** Compute global and component health (market_data, market_updater, signal_monitor, telegram, trade_system, db) for monitoring and alerts.
- **Files:** `backend/app/services/system_health.py`, `backend/app/main.py` (routes for `/api/health`, `/ping_fast`, `/__ping`), `backend/app/api/routes_monitoring.py` (e.g. `/api/health/system` if mounted there), health routes under main or monitoring router.
- **Status:** **Active.** Used by Docker healthchecks, verify.sh, health_snapshot_log.sh, deploy_smoke_check, docs.
- **Evidence:** `system_health.py` defines `get_system_health(db)` with DB timeout, component checks, and global_status PASS/WARN/FAIL. `main.py` lines 649–735 expose `/__ping`, `ping_fast`, `/api/health`, `/api/ping_fast`. Nginx maps `/api/health` → `__ping`.

### 2.2 Backend health fix and repair endpoints

- **Name:** POST /api/health/fix, POST /api/health/repair
- **Purpose:** Fix: restart in-process services (exchange_sync, signal_monitor, trading_scheduler) only; no schema change. Repair: ensure optional columns and tables (e.g. order_intents); requires x-api-key.
- **Files:** `backend/app/api/routes_control.py` (health/fix), `backend/app/api/routes_monitoring.py` (health/repair).
- **Status:** **Active.** heal.sh and remediate_market_data.sh (optional) call health/fix.
- **Evidence:** routes_control.py ~551–605: `fix_backend_health()` stops then restarts the three services. routes_monitoring.py ~215–230: `health_repair` calls `ensure_optional_columns(engine)`.

### 2.3 Self-heal (verify + heal + run, systemd timer)

- **Name:** ATP self-heal (scripts/selfheal)
- **Purpose:** Periodically verify disk &lt;90%, no unhealthy containers, API ok, db/market_data/market_updater/signal_monitor PASS; on failure run heal (disk cleanup and/or stack restart + POST /api/health/fix + nginx reload).
- **Files:** `scripts/selfheal/verify.sh`, `scripts/selfheal/heal.sh`, `scripts/selfheal/run.sh`, `scripts/selfheal/systemd/atp-selfheal.service`, `scripts/selfheal/systemd/atp-selfheal.timer`, `scripts/selfheal/README.md`, `docs/runbooks/EC2_SELFHEAL_DEPLOY.md`.
- **Status:** **Active** (if deployed on EC2 per runbook). Timer every 2 minutes; heal uses flock lock.
- **Evidence:** verify.sh exits 2–8 for DISK, CONTAINERS_UNHEALTHY, API_HEALTH, DB, MARKET_DATA, MARKET_UPDATER, SIGNAL_MONITOR; heal.sh does heal_disk (truncate logs, prune, journal vacuum, etc.) and heal_services (compose up, POST health/fix, nginx reload). atp-selfheal.timer: OnCalendar=*:0/2, OnBootSec=60.

### 2.4 Health snapshot and Telegram alert (streak-fail + remediation)

- **Name:** Health snapshot log + Telegram alert with remediation
- **Purpose:** Every 5 min append a one-line snapshot to `/var/log/atp/health_snapshots.log`; separate timer runs health_snapshot_telegram_alert.sh which applies streak_fail_3 rule, runs targeted remediation (remediate_market_data.sh) for MARKET_DATA/market_updater failures, sends Telegram alerts with dedupe/cooldown and optional “resolved” message.
- **Files:** `scripts/diag/health_snapshot_log.sh`, `scripts/diag/health_snapshot_telegram_alert.sh`, `scripts/selfheal/systemd/atp-health-snapshot.service|timer`, `scripts/selfheal/systemd/atp-health-alert.service|timer`, `scripts/selfheal/remediate_market_data.sh`, `backend/app/services/health_alert_incident.py`, `docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md`.
- **Status:** **Active** (if systemd units installed on EC2). Alert script uses health_alert_incident for dedupe and remediation policy.
- **Evidence:** health_snapshot_log.sh calls verify.sh and curl `/api/health/system`, writes JSONL. health_snapshot_telegram_alert.sh reads log, uses IncidentDecision (health_alert_incident), runs remediate_market_data.sh (restart market-updater-aws, POST update-cache, optionally health/fix), sends Telegram. Timers: OnCalendar=*:0/5, OnBootSec=120.

### 2.5 Targeted market-data remediation script

- **Name:** remediate_market_data.sh
- **Purpose:** For MARKET_DATA/market_updater FAIL: restart market-updater-aws, wait, POST /api/market/update-cache (with retries), optionally POST /api/health/fix after cache (default skip to avoid empty reply during backend restart).
- **Files:** `scripts/selfheal/remediate_market_data.sh`.
- **Status:** **Active.** Invoked from health_snapshot_telegram_alert.sh.
- **Evidence:** Script restarts container, sleeps 10s, calls update-cache with configurable timeout/retries; ATP_REMEDIATE_RUN_HEALTH_FIX=1 to run health/fix after.

### 2.6 Docker Compose healthchecks and restart policies

- **Name:** Container healthchecks and restart policy
- **Purpose:** Docker restarts unhealthy or exited containers; healthchecks use backend `/api/health` or `ping_fast`, db pg_isready, frontend wget.
- **Files:** `docker-compose.yml`.
- **Status:** **Active.**
- **Evidence:** backend: healthcheck with urlopen('http://localhost:8002/api/health') or ping_fast; market-updater-aws, frontend-aws, db use healthcheck; restart: always or unless-stopped for main services.

### 2.7 GitHub Actions prod health check

- **Name:** Prod Health Check workflow
- **Purpose:** Verify PROD API reachable (HTTP 200) on schedule (every 6h) and on push to main.
- **Files:** `.github/workflows/prod-health-check.yml`.
- **Status:** **Active.**
- **Evidence:** Curls PROD_HEALTH_URL (default https://dashboard.hilovivo.com/api/health), exits 1 if not 200, writes step summary.

### 2.8 OpenClaw / agent recovery (autonomous recovery)

- **Name:** Agent recovery layer
- **Purpose:** Automatically recover from known low-risk orchestration failures (e.g. task stuck in deploying, orphan smoke check, revalidate patching, missing artifact) without human intervention; controlled by AGENT_RECOVERY_ENABLED.
- **Files:** `backend/app/services/agent_recovery.py`, `docs/architecture/OPENCLAW_AUTONOMOUS_RECOVERY_DESIGN.md`.
- **Status:** **Active** (when agent scheduler runs and recovery enabled). Not host/container health; task-lifecycle recovery.
- **Evidence:** agent_recovery.py: run_orphan_smoke_check_playbook, revalidate patching, etc.; invoked from agent scheduler; uses run_and_record_smoke_check from deploy_smoke_check.

### 2.9 Deploy smoke check (post-deploy health validation)

- **Name:** Deploy smoke check
- **Purpose:** After deploy (e.g. webhook or Telegram “smoke check”): liveness via ping_fast, then /api/health/system with retries; record result and optionally advance Notion task to done.
- **Files:** `backend/app/services/deploy_smoke_check.py`, used by agent_task_executor, routes_agent, routes_github_webhook, telegram_commands (smoke_check button).
- **Status:** **Active.** Used for deployment health validation and task advancement.
- **Evidence:** run_smoke_check() waits for backend, then checks system_health; record_smoke_check_result blocks or advances task.

### 2.10 Nightly integrity audit (EC2)

- **Name:** Nightly integrity audit
- **Purpose:** Run on EC2 at 03:15 local time: ensure_stack_up, system health check, health_guard, portfolio consistency, etc.; on failure send one Telegram alert (step name + git hash).
- **Files:** `scripts/aws/nightly_integrity_audit.sh`, `scripts/aws/systemd/nightly-integrity-audit.service|timer`, `scripts/aws/_notify_telegram_fail.sh`, `docs/runbooks/EC2_NIGHTLY_INTEGRITY_AUDIT.md`.
- **Status:** **Active** if timer installed on EC2 (see phase6 and runbooks).
- **Evidence:** Timer OnCalendar=*-*-* 03:15:00; script runs multiple checks and notifies on first failure.

### 2.11 Health guard (CI / verification)

- **Name:** health_guard.sh
- **Purpose:** Simple sanity check: if backend-aws is present, curl /health (not /api/health) up to 5 times; output PASS or FAIL. Used in verification scripts.
- **Files:** `scripts/aws/health_guard.sh`.
- **Status:** **Active** as a verification helper. Not a continuous watchdog.
- **Evidence:** Probes http://127.0.0.1:8002/health (backend may expose /health or proxy; doc references __ping).

### 2.12 Telegram health helper and system alerts

- **Name:** Telegram health check and system alerts
- **Purpose:** Check Telegram config (RUN_TELEGRAM, token, chat_id) and record send results for system health; 24h-throttled system-down alerts.
- **Files:** `backend/app/services/telegram_health.py`, `backend/app/services/telegram_notifier.py` (record_telegram_send_result), `backend/app/services/system_health.py` (uses it), system_alerts / market_updater / signal_monitor wiring.
- **Status:** **Active.** Used by system_health and alerting.
- **Evidence:** telegram_health.py check_telegram_health(); system_health uses _check_telegram_health(); record_telegram_send_result in telegram_notifier.

---

## 3. Suspected Existing Components

### 3.1 Health monitor (bash, systemd) — possible overlap with selfheal

- **Name:** health_monitor.sh + health_monitor.service
- **Why it looks related:** Continuous loop every 60s; checks Docker service health, restarts unhealthy, rebuilds after 3 attempts; restarts db and Nginx. Same goal as selfheal (recover services).
- **Files:** `scripts/health_monitor.sh`, `scripts/health_monitor.service`, `install_health_monitor.sh`, `README_HEALTH_MONITOR.md`.
- **What is missing to confirm:** Whether it is actually installed and running on LAB/PROD. install_health_monitor.sh uses hardcoded HOST=ubuntu@175.41.189.249 (old IP?). If both health_monitor and atp-selfheal.timer run, they could double-restart.

### 3.2 Python health monitor (cron) — alternate implementation

- **Name:** infra/monitor_health.py + install_health_cron.sh
- **Why it looks related:** Monitors containers and HTTP endpoints every 5 min via cron; sends Telegram on failure; can restart services. Same conceptual role as health_snapshot + alert and health_monitor.sh.
- **Files:** `infra/monitor_health.py`, `infra/install_health_cron.sh`, `infra/telegram_helper` (send_telegram_message).
- **What is missing to confirm:** Whether cron is installed on any current host. Doc says “run via cron every 5 minutes”. If used alongside atp-health-alert timer and health_monitor, three layers would do similar things.

### 3.3 Dashboard health check (data quality) — separate concern

- **Name:** dashboard_health_check.sh + timer
- **Purpose:** Data quality: /api/market/top-coins-data, min coins, Telegram on failure. Different from “system health” (up/down).
- **Files:** `scripts/dashboard_health_check.sh`, `scripts/dashboard_health_check.service`, `scripts/dashboard_health_check.timer`, `install_dashboard_health_check.sh`, `README_DASHBOARD_HEALTH_CHECK.md`.
- **What is missing to confirm:** Whether timer is installed on LAB/PROD; script contains redacted TELEGRAM placeholders (security/maintainability).

### 3.4 CloudWatch / external monitoring

- **Why it looks related:** docs/monitoring/HEALTH_MONITORING.md describes Option 2: CloudWatch Synthetics canary + alarm for /api/health/system. No repo files define the canary or alarm.
- **Files:** Documentation only in `docs/monitoring/HEALTH_MONITORING.md`.
- **What is missing to confirm:** Whether a canary/alarm was ever created in AWS (not in repo).

### 3.5 UptimeRobot or other external HTTP monitor

- **Why it looks related:** Same doc recommends UptimeRobot (or similar) on https://dashboard.hilovivo.com/api/health/system.
- **What is missing to confirm:** Whether it is configured (external to repo).

---

## 4. Gaps

- **Unified “one watchdog” story:** There are several parallel mechanisms (health_monitor.sh, atp-selfheal, atp-health-snapshot + alert, optional cron for monitor_health.py, Docker restart). No single doc or diagram that states “this is the canonical health/recovery stack” and “these are disabled/superseded.”
- **Installation and host consistency:** install_health_monitor.sh uses a hardcoded IP; EC2_SELFHEAL_DEPLOY and runbooks refer to ~/automated-trading-platform and ubuntu user. LAB vs PROD and which timers/services are actually enabled is not codified in repo (only in runbooks/checklists).
- **Backend /health vs /api/health:** health_guard.sh curls `/health`; nginx and main app expose `/api/health` → `__ping` and `/api/health/system`. Clarification of canonical liveness URL (e.g. always use `/api/health` or `ping_fast`) would avoid confusion.
- **Telegram alert dedupe and escalation:** health_snapshot_telegram_alert + health_alert_incident implement cooldown and streak rules; other scripts (dashboard_health_check, monitor_health.py) may send independently — no single “alert manager” to avoid duplicate or conflicting notifications.
- **Disk/memory cleanup:** heal.sh and docs (e.g. PROD_DISK_RESIZE) mention disk cleanup; infra/install_cleanup_cron.sh and cleanup_disk.sh exist. It’s not clear if cleanup cron is installed on LAB/PROD or if only selfheal handles disk.
- **Deployment health validation:** Post-deploy smoke check is implemented (deploy_smoke_check + webhook/Telegram); no separate “deployment health gate” runbook that ties together smoke check, verify.sh, and /api/health/system in one checklist for LAB/PROD.

---

## 5. Duplication Risk Map

- **Restart logic:** Building a new “watchdog” that restarts containers or backend services would duplicate: (1) Docker’s own restart policy and healthcheck, (2) heal.sh (stack + health/fix), (3) remediate_market_data.sh (market-updater-aws + update-cache), (4) health_monitor.sh (restart/rebuild per service). **Reuse:** Prefer calling existing scripts (verify.sh, heal.sh, remediate_market_data.sh) or POST /api/health/fix instead of reimplementing restarts.
- **Health evaluation:** Any new component that decides “is the system healthy?” should use existing: (1) GET /api/health/system (backend), (2) verify.sh (ops view: disk, containers, api, db, market_data, market_updater, signal_monitor). **Reuse:** Call these endpoints/scripts; avoid a third definition of “healthy.”
- **Telegram alerts on failure:** health_snapshot_telegram_alert.sh (with incident dedupe), optional monitor_health.py, dashboard_health_check.sh, nightly_integrity_audit (Telegram on first failing step). **Reuse:** Prefer extending the existing alert pipeline (e.g. same STATE_FILE and rules) or clearly disabling one of the existing ones to avoid duplicate alerts.
- **Scheduling (cron vs systemd):** Both cron (install_health_cron.sh, install_cleanup_cron) and systemd timers (atp-selfheal, atp-health-snapshot, atp-health-alert, nightly-integrity-audit, dashboard_health_check) exist. **Reuse:** Prefer systemd timers for new scheduled health/recovery jobs and document which cron entries (if any) are still in use on which host.
- **In-process service restart:** POST /api/health/fix already restarts exchange_sync, signal_monitor, trading_scheduler. **Reuse:** Any “restart backend services without container restart” should use this endpoint.

---

## 6. Recommended Next Audit Steps

- **On LAB and PROD EC2 (or current deployment host):**
  1. List systemd timers: `systemctl list-timers --all | grep -E 'atp|health|nightly|dashboard'` and confirm which are enabled/active.
  2. List cron: `crontab -l` (ubuntu and root if applicable) and check for monitor_health.py, cleanup, or other health-related entries.
  3. Check running services: `systemctl status health_monitor.service atp-selfheal.timer atp-health-snapshot.timer atp-health-alert.timer nightly-integrity-audit.timer dashboard_health_check.timer` (as applicable).
  4. Confirm selfheal: `journalctl -u atp-selfheal.service -n 50` and verify.sh/heal.sh paths and last run outcome (PASS/HEALED/STILL_FAIL).
  5. Confirm health snapshot: Check `/var/log/atp/health_snapshots.log` exists and is recently written; check atp-health-alert service journal for Telegram send/dedupe.
  6. Confirm backend: `curl -sS http://127.0.0.1:8002/api/health` and `curl -sS http://127.0.0.1:8002/api/health/system | jq .global_status,.market_updater.status`.
  7. Check for lock file: `ls -la /var/lock/atp-selfheal.lock` and that heal runs under expected user.
  8. Document which of health_monitor.service, atp-selfheal, atp-health-*, nightly-integrity, dashboard_health_check are intentionally enabled and which (if any) are legacy/disabled.

- **In GitHub/Actions:**
  1. Confirm prod-health-check workflow is enabled and runs (schedule + push); check last run and PROD_HEALTH_URL.

- **External:**
  1. If CloudWatch Synthetics or UptimeRobot are mentioned in runbooks, verify they exist in AWS/third-party and point at the intended URL (e.g. /api/health/system).

---

## 7. Best Reuse Candidates

- **Backend:** `get_system_health(db)` and **GET /api/health/system** — single source of truth for component and global status. Use for any new dashboard, script, or alarm.
- **POST /api/health/fix** — use for “restart in-process services” from any script or automation; avoid reimplementing stop/start of exchange_sync, signal_monitor, trading_scheduler.
- **scripts/selfheal/verify.sh** — use for “ops view” of health (disk, containers, api, db, market_data, market_updater, signal_monitor). Extend with new checks if needed rather than a parallel “verify” script.
- **scripts/selfheal/heal.sh** — use for full host-level recovery (disk + stack + health/fix + nginx). Call it from a new scheduler only if you need a different schedule or trigger; otherwise use existing atp-selfheal.timer.
- **scripts/selfheal/remediate_market_data.sh** — use for “market data / market updater” failures; already integrated with health_snapshot_telegram_alert.
- **health_alert_incident.py** — use for incident dedupe and remediation policy (streak, cooldown, resolved message) if adding new Telegram health alerts.
- **Deploy smoke check:** `run_smoke_check` / `run_and_record_smoke_check` — use for post-deploy validation; already used by webhook and Telegram; do not add a second “deploy health” flow without reusing this.

---

## Summary: Files and Folders Most Relevant to Health and Remediation

**Backend**
- `backend/app/services/system_health.py`
- `backend/app/services/health_alert_incident.py`
- `backend/app/services/telegram_health.py`
- `backend/app/api/routes_control.py` (health/fix)
- `backend/app/api/routes_monitoring.py` (health/repair, possibly health/system)
- `backend/app/main.py` (ping, health routes)
- `backend/app/services/deploy_smoke_check.py`
- `backend/app/services/agent_recovery.py`

**Scripts**
- `scripts/selfheal/` (verify.sh, heal.sh, run.sh, remediate_market_data.sh, systemd units, README)
- `scripts/diag/health_snapshot_log.sh`, `scripts/diag/health_snapshot_telegram_alert.sh`
- `scripts/health_monitor.sh`, `scripts/health_monitor.service`
- `scripts/dashboard_health_check.sh`, `scripts/dashboard_health_check.service`, `scripts/dashboard_health_check.timer`
- `scripts/aws/health_guard.sh`, `scripts/aws/nightly_integrity_audit.sh`, `scripts/aws/systemd/nightly-integrity-audit.*`
- `install_health_monitor.sh`, `install_dashboard_health_check.sh`

**Infra**
- `infra/monitor_health.py`, `infra/install_health_cron.sh`

**Compose**
- `docker-compose.yml` (healthcheck, restart, depends_on)

**CI**
- `.github/workflows/prod-health-check.yml`

**Docs**
- `docs/runbooks/EC2_SELFHEAL_DEPLOY.md`, `docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md`, `docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md`, `docs/runbooks/EC2_NIGHTLY_INTEGRITY_AUDIT.md`
- `docs/monitoring/HEALTH_MONITORING.md`, `docs/AWS_HEALTH_MONITORING_SUMMARY.md`, `docs/AWS_HEALTH_MONITORING_TOOLS.md`
- `README_HEALTH_MONITOR.md`, `README_DASHBOARD_HEALTH_CHECK.md`, `docs/SYSTEM_HEALTH_IMPLEMENTATION.md`

---

## Runtime Checks to Perform on LAB and PROD

1. `systemctl list-timers --all` and `systemctl status` for: atp-selfheal.timer, atp-health-snapshot.timer, atp-health-alert.timer, nightly-integrity-audit.timer, dashboard_health_check.timer, health_monitor.service (if present).
2. `crontab -l` (ubuntu and root) for monitor_health.py, cleanup, or health-related lines.
3. `curl -sS http://127.0.0.1:8002/api/health` and `curl -sS http://127.0.0.1:8002/api/health/system | jq .`
4. `./scripts/selfheal/verify.sh; echo "exit=$?"` from repo root.
5. `sudo journalctl -u atp-selfheal.service -n 80 --no-pager` and same for atp-health-snapshot, atp-health-alert, nightly-integrity-audit.
6. Presence and recent writes of `/var/log/atp/health_snapshots.log`, `/var/lib/atp/health_alert_state.json`, and log dir for health_monitor if used.
7. `docker compose --profile aws ps` and health column for backend-aws, market-updater-aws, db, frontend-aws.

---

## Single Safest Next Step Before Implementing Anything New

**Confirm runtime reality on LAB and PROD:** Run the checks in Section 6 and the “Runtime checks” list above, and record which of the following are actually enabled and running: health_monitor.service, atp-selfheal.timer, atp-health-snapshot.timer, atp-health-alert.timer, nightly-integrity-audit.timer, dashboard_health_check.timer, and any health-related cron jobs. Produce a one-page “current health/recovery stack” (what runs where, and at what interval). Use that as the baseline before adding or changing any new health/recovery/watchdog logic, so that nothing duplicates or conflicts with what is already in production.
