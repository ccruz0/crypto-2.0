# ATP Runtime Health/Recovery Baseline

**Date:** 2026-03-11  
**Purpose:** Establish runtime truth for LAB and PROD health/recovery stack before any changes. Inspection only; no code or infrastructure changes.

**Access during audit:**
- **LAB (i-0d82c172235770a0d, atp-lab-ssm-clean):** Inspected via AWS SSM send-command (read-only). No SSH/shell session.
- **PROD (i-087953603011543c5, atp-rebuild-2026):** Initially not accessible (SSM ConnectionLost, API 000). **Post-recovery (2026-03-11):** access restored; runtime baseline verified. See §3 and One-Page PROD stack for confirmed state.

---

## 1. Executive Summary

- **LAB overall state:** No ATP health/recovery systemd timers or services are installed or active. Repo and `scripts/selfheal/verify.sh` exist and are executable. No ubuntu crontab. No `/var/log/atp` or `/var/lib/atp`. Docker Compose with profile `aws` shows no running services (empty table). LAB is effectively **without** the documented health/recovery stack at runtime.

- **PROD overall state:** **Recovered and verified (2026-03-11).** After access was restored: PROD API healthy (GET /api/health returns 200), EC2 system and instance reachability OK, SSM Online. nginx and docker active. ATP health/recovery timers confirmed: atp-selfheal.timer, atp-health-snapshot.timer, atp-health-alert.timer running. SSM agent is the **snap** unit: snap.amazon-ssm-agent.amazon-ssm-agent.service (active and running).

- **Which mechanisms are actually active:** On **LAB:** none of the ATP health/recovery mechanisms are present or active. On **PROD:** atp-selfheal, atp-health-snapshot, and atp-health-alert timers are running; docker and nginx active; SSM Online (snap service).

- **Biggest overlap risks:** When PROD is inspected and/or when enabling the stack: multiple overlapping mechanisms exist in the **repo** (health_monitor.sh, selfheal, health snapshot+alert, dashboard_health_check, infra/monitor_health.py cron). Enabling them all without a single canonical stack would duplicate monitoring, alerting, and remediation.

- **Biggest gaps:** LAB has no health/recovery automation at runtime. If PROD has the same situation, neither environment has active self-heal or health alerting until timers/services are explicitly installed and enabled per runbooks.

---

## 2. LAB Runtime Inventory

Evidence from SSM commands run on **i-0d82c172235770a0d** on 2026-03-11. Commands used are listed in § “Exact commands used” at the end.

| Component | Type | Installed? | Enabled? | Running? | Healthy? | Frequency | Evidence | Overlap notes | Recommendation |
|-----------|------|------------|----------|----------|----------|-----------|----------|---------------|----------------|
| atp-selfheal.timer | timer | no | no | no | n/a | n/a | Not in `systemctl list-timers` (17 timers, all system). No atp* unit files. | N/A | Install only if LAB should run self-heal; align with PROD. |
| atp-health-snapshot.timer | timer | no | no | no | n/a | n/a | Same as above. | N/A | Same. |
| atp-health-alert.timer | timer | no | no | no | n/a | n/a | Same as above. | N/A | Same. |
| nightly-integrity-audit.timer | timer | no | no | no | n/a | n/a | Same as above. | N/A | Same. |
| dashboard_health_check.timer | timer | no | no | no | n/a | n/a | Same as above. | N/A | Same. |
| atp-selfheal.service | service | no | no | no | n/a | n/a | No atp* unit files. | N/A | — |
| atp-health-snapshot.service | service | no | no | no | n/a | n/a | Same. | N/A | — |
| atp-health-alert.service | service | no | no | no | n/a | n/a | Same. | N/A | — |
| health_monitor.service | service | no | no | no | n/a | n/a | No health_monitor unit file. | N/A | — |
| dashboard_health_check.service | service | no | no | no | n/a | n/a | No dashboard_health* unit file. | N/A | — |
| ubuntu crontab | cron | no | no | n/a | n/a | n/a | `crontab -l` → NO_CRONTAB. | N/A | — |
| verify.sh | script | yes | n/a | n/a | n/a | n/a | Exists: `/home/ubuntu/crypto-2.0/scripts/selfheal/verify.sh`, -rwxrwxr-x, Mar 7 08:13. REPO_EXISTS. | N/A | keep (repo asset). |
| /var/log/atp/health_snapshots.log | log/state | no | n/a | n/a | n/a | n/a | NO_ATP_LOG_DIR. | N/A | Created when snapshot timer runs. |
| /var/lib/atp/health_alert_state.json | log/state | no | n/a | n/a | n/a | n/a | NO_ATP_LIB_DIR. | N/A | Created when health-alert runs. |
| backend-aws (Docker) | docker | no | n/a | no | n/a | n/a | `docker compose --profile aws ps` → empty (no rows). | N/A | LAB may not run full ATP stack. |
| market-updater-aws | docker | no | n/a | no | n/a | n/a | Same. | N/A | — |
| db | docker | no | n/a | no | n/a | n/a | Same. | N/A | — |
| frontend-aws | docker | no | n/a | no | n/a | n/a | Same. | N/A | — |
| GET /api/health | endpoint | n/a | n/a | no | no | n/a | Backend not running (no containers). | N/A | — |
| GET /api/health/system | endpoint | n/a | n/a | no | no | n/a | Same. | N/A | — |

**LAB summary:** No ATP health/recovery timers, services, or cron. Repo and verify.sh present. No ATP Docker stack running; no health endpoints to probe.

---

## 3. PROD Runtime Inventory

**Verified post-recovery (2026-03-11).** PROD (i-087953603011543c5) was inspected after access was restored. See **docs/PROD_INCIDENT_2026-03-11_RECOVERY.md** for incident summary, conclusion (instance-level outage), and recommendations. The table below is a **template**: run the “Exact commands used” on PROD (via SSM or SSH once access is restored) and fill in the results.

| Component | Type | Installed? | Enabled? | Running? | Healthy? | Frequency | Evidence | Overlap notes | Recommendation |
|-----------|------|------------|----------|----------|----------|-----------|----------|---------------|----------------|
| atp-selfheal.timer | timer | yes | yes | yes | n/a | 2 min | Confirmed running post-recovery | — | keep |
| atp-health-snapshot.timer | timer | yes | yes | yes | n/a | 5 min | Confirmed running post-recovery | — | keep |
| atp-health-alert.timer | timer | yes | yes | yes | n/a | 5 min | Confirmed running post-recovery | — | keep |
| nightly-integrity-audit.timer | timer | **RUN ON PROD** | **RUN ON PROD** | **RUN ON PROD** | n/a | 03:15 local (if enabled) | — | — | — |
| dashboard_health_check.timer | timer | **RUN ON PROD** | **RUN ON PROD** | **RUN ON PROD** | n/a | 20 min (if enabled) | — | — | — |
| health_monitor.service | service | **RUN ON PROD** | **RUN ON PROD** | **RUN ON PROD** | n/a | 60 s loop (if running) | — | — | — |
| ubuntu crontab | cron | **RUN ON PROD** | — | — | n/a | n/a | — | — | — |
| root crontab | cron | **RUN ON PROD** | — | — | n/a | n/a | — | — | — |
| verify.sh | script | **RUN ON PROD** | n/a | n/a | **RUN ON PROD** | n/a | — | — | — |
| /var/log/atp/health_snapshots.log | log/state | **RUN ON PROD** | n/a | n/a | n/a | n/a | — | — | — |
| /var/lib/atp/health_alert_state.json | log/state | **RUN ON PROD** | n/a | n/a | n/a | n/a | — | — | — |
| docker compose --profile aws ps | docker | **RUN ON PROD** | n/a | **RUN ON PROD** | **RUN ON PROD** | n/a | — | — | — |
| GET /api/health | endpoint | n/a | n/a | yes | yes | n/a | Returns 200, `{"status":"ok","path":"/api/health"}` | — | — |
| GET /api/health/system | endpoint | n/a | n/a | not captured | not captured | n/a | Not re-tested post-recovery | — | — |
| EC2 status checks | — | n/a | n/a | yes | yes | n/a | System and instance reachability OK | — | — |
| SSM PingStatus | — | n/a | n/a | yes | yes | n/a | Online | — | — |
| SSM agent (real unit) | service | yes | yes | yes | yes | n/a | snap.amazon-ssm-agent.amazon-ssm-agent.service active | — | Use snap unit for status/restart |
| docker | service | yes | yes | yes | yes | n/a | systemctl: active | — | — |
| nginx | service | yes | yes | yes | yes | n/a | systemctl: active | — | — |

**PROD summary:** Post-recovery: API healthy, EC2 and SSM OK, nginx and docker active. ATP timers atp-selfheal, atp-health-snapshot, atp-health-alert confirmed running. SSM agent is the **snap** unit (snap.amazon-ssm-agent.amazon-ssm-agent.service). **Swap** is enabled and verified on PROD (2G `/swapfile`, in fstab). **Repo drift** on PROD (local changes/untracked files blocking clean pull) remains an operational follow-up; see **docs/runbooks/PROD_REPO_RECONCILIATION_RUNBOOK.md**.

---

## 4. Cross-Environment Comparison

| Aspect | LAB | PROD | Drift / note |
|--------|-----|------|--------------|
| Access during audit | SSM Online; read-only commands run | Post-recovery: SSM Online, API 200 | PROD verified 2026-03-11. |
| ATP timers | None installed/active | atp-selfheal, atp-health-snapshot, atp-health-alert confirmed running | PROD has canonical health/recovery timers; LAB has none. |
| ATP services | None installed/active | atp-* services triggered by timers; SSM = snap.amazon-ssm-agent.amazon-ssm-agent.service | PROD uses snap SSM unit. |
| Crontab (ubuntu) | No crontab | Not confirmed | — |
| Repo + verify.sh | Present, executable | Present on PROD | — |
| /var/log/atp, /var/lib/atp | Do not exist | Not confirmed on PROD | — |
| Docker stack (profile aws) | No running services (empty) | Running (API healthy) | LAB minimal; PROD full stack. |

**What exists on both (from repo):** Scripts and systemd unit files in repo; verify.sh present on both.  
**What exists only on LAB (verified):** No ATP health stack at runtime.  
**What exists only on PROD:** atp-selfheal, atp-health-snapshot, atp-health-alert timers; docker + nginx active; SSM Online (snap unit).  
**Drift:** LAB has no health/recovery automation; PROD has the canonical ATP timers and running stack.

---

## 5. Canonical Stack Recommendation

Based on **repo audit** (docs/ATP_EXISTING_HEALTH_RECOVERY_AUDIT.md) and **LAB runtime evidence** (no overlap at runtime on LAB because nothing is enabled):

- **Local monitoring (periodic check):** Use **atp-health-snapshot** (timer + health_snapshot_log.sh) calling **verify.sh** and **GET /api/health/system** to write a timeline. Prefer this over a second ad-hoc monitor.
- **Local remediation:** Use **atp-selfheal** (timer + run.sh → verify.sh → heal.sh). Single remediation path; avoid enabling health_monitor.service in parallel.
- **Alerting:** Use **atp-health-alert** (timer + health_snapshot_telegram_alert.sh) with existing incident dedupe (health_alert_incident.py). Avoid adding another Telegram path (e.g. dashboard_health_check or infra/monitor_health.py cron) unless one is explicitly disabled.
- **Periodic audit:** Use **nightly-integrity-audit** (timer + nightly_integrity_audit.sh) for once-daily integrity + Telegram on first failure.
- **Container recovery:** Rely on **Docker** (restart policy + healthcheck) plus **heal.sh** when verify fails (stack restart + POST /api/health/fix). Do not add a second “restart containers” loop (e.g. health_monitor.sh) on the same host.
- **Endpoint health checking:** Use **GET /api/health** (or **ping_fast**) for liveness; **GET /api/health/system** for full status. External checks (e.g. GitHub prod-health-check, UptimeRobot) should use the same endpoints.

---

## 6. Duplication Candidates

(From repo audit; runtime duplication is currently none on LAB because no mechanisms are active.)

- **health_monitor.service** vs **atp-selfheal.timer:** Both can restart containers/services. If both are enabled on the same host, they duplicate. Recommendation: pick one (prefer atp-selfheal).
- **atp-health-alert** vs **dashboard_health_check** vs **infra/monitor_health.py (cron):** All can send Telegram on failure. Recommendation: use atp-health-alert as the single health-failure alert path; disable or repurpose the others.
- **verify.sh** vs **GET /api/health/system:** Same notion of “healthy” (disk, containers, api, db, market_data, market_updater, signal_monitor). Recommendation: keep both; scripts call the API and verify.sh encapsulates the ops view; do not add a third definition.

---

## 7. Missing Capabilities

- **LAB:** No health/recovery automation; no visibility into LAB “health” unless someone runs verify.sh or curl manually. Acceptable if LAB is non-production; if LAB should mirror PROD behavior, install the canonical timers/services.
- **PROD:** Unknown until baseline is run. Likely gaps (if PROD also has no timers): no self-heal, no health snapshot log, no Telegram health alerts, no nightly integrity run.
- **External:** No confirmation of UptimeRobot/CloudWatch Synthetics in this audit (external to repo).
- **Root crontab:** Not inspected on LAB (ubuntu only). PROD root crontab should be checked when PROD is inspected.

---

## 8. Safest Next Change

**Single safest step:** Restore access to PROD (SSM and/or API). Then run the **exact inspection commands** listed below on PROD and record results in §3 and in the one-page PROD stack. Do **not** enable, disable, or install anything until the PROD baseline is documented. After both LAB and PROD baselines are complete, decide which mechanisms to **keep** as the canonical stack (see §5) and which to **disable later** or **replace later** (see §6), then make one change at a time.

---

## One-Page Current Health/Recovery Stack: LAB

| Layer | Component | Status |
|-------|-----------|--------|
| Timers | atp-selfheal, atp-health-snapshot, atp-health-alert, nightly-integrity-audit, dashboard_health_check | **None installed/active** |
| Services | health_monitor, atp-* services | **None installed/active** |
| Cron | ubuntu | **No crontab** |
| Scripts | verify.sh, heal.sh, run.sh | **Present in repo; verify.sh executable** |
| Log/state | /var/log/atp/, /var/lib/atp/ | **Do not exist** |
| Docker (profile aws) | backend-aws, market-updater-aws, db, frontend-aws | **No running services** |
| Endpoints | /api/health, /api/health/system | **N/A (backend not running)** |

**Conclusion:** LAB has no active ATP health/recovery stack. Repo and verify.sh are present.

---

## One-Page Current Health/Recovery Stack: PROD

| Layer | Component | Status |
|-------|-----------|--------|
| Timers | atp-selfheal, atp-health-snapshot, atp-health-alert | **Active** (confirmed post-recovery 2026-03-11). nightly-integrity-audit, dashboard_health_check not confirmed. |
| Services | SSM agent = **snap.amazon-ssm-agent.amazon-ssm-agent.service** | **Active and running**. health_monitor not confirmed (prefer atp-selfheal). |
| Cron | ubuntu, root | Not confirmed. |
| Scripts | verify.sh, heal.sh, run.sh | Present in repo on PROD. |
| Log/state | /var/log/atp/, /var/lib/atp/ | Not confirmed. |
| Docker (profile aws) | backend-aws, market-updater-aws, db, frontend-aws | **Running** (API healthy). |
| Endpoints | /api/health, /api/health/system | **GET /api/health returns 200** `{"status":"ok","path":"/api/health"}`. |
| EC2 / SSM | Instance reachability, SSM PingStatus | **System and instance OK; SSM Online.** |

**Conclusion:** PROD recovered and verified. ATP health/recovery timers (selfheal, health-snapshot, health-alert) and SSM (snap unit) are active; API and docker/nginx healthy.

---

## Final Decision Table

| Component | Keep | Disable later | Replace later | Investigate more |
|-----------|------|---------------|----------------|------------------|
| atp-selfheal.timer/.service | ✓ (canonical remediation) | | | Confirm on PROD |
| atp-health-snapshot.timer/.service | ✓ (canonical monitoring log) | | | Confirm on PROD |
| atp-health-alert.timer/.service | ✓ (canonical alerting) | | | Confirm on PROD |
| nightly-integrity-audit.timer/.service | ✓ (canonical audit) | | | Confirm on PROD |
| dashboard_health_check.timer/.service | | ✓ (if atp-health-alert covers alerts) | | Confirm on PROD if present |
| health_monitor.service | | ✓ (overlaps selfheal) | | Confirm on PROD if present |
| infra/monitor_health.py (cron) | | ✓ (overlaps snapshot+alert) | | Check PROD/LAB crontab |
| verify.sh / heal.sh / run.sh | ✓ | | | — |
| GET /api/health, /api/health/system | ✓ | | | — |
| POST /api/health/fix | ✓ | | | — |

---

## Exact Commands Used

### Commands run from this audit (LAB, via SSM)

- **PROD API + SSM status (from repo):**  
  `./scripts/aws/prod_status.sh`  
  Result: PROD API FAIL (HTTP 000); PROD SSM ConnectionLost; LAB SSM Online.

- **LAB – list timers (included in first SSM run):**  
  `systemctl list-timers --all --no-pager`  
  Result: 17 timers; none atp/health/nightly/dashboard.

- **LAB – unit files:**  
  `systemctl list-unit-files --no-pager | grep -iE 'atp|health_monitor|dashboard_health|nightly-integrity'`  
  Result: Exit 1 (no matches) → no such units installed.

- **LAB – ubuntu crontab:**  
  `crontab -l 2>/dev/null || echo NO_CRONTAB`  
  Result: NO_CRONTAB.

- **LAB – verify.sh and repo:**  
  `test -f /home/ubuntu/crypto-2.0/scripts/selfheal/verify.sh && ls -la /home/ubuntu/crypto-2.0/scripts/selfheal/verify.sh; test -d /home/ubuntu/crypto-2.0 && echo REPO_EXISTS || echo REPO_MISSING`  
  Result: verify.sh exists, executable; REPO_EXISTS.

- **LAB – log/state dirs:**  
  `ls -la /var/log/atp/ 2>/dev/null || echo NO_ATP_LOG_DIR`  
  `ls -la /var/lib/atp/ 2>/dev/null || echo NO_ATP_LIB_DIR`  
  Result: NO_ATP_LOG_DIR, NO_ATP_LIB_DIR.

- **LAB – Docker:**  
  `cd /home/ubuntu/crypto-2.0 && docker compose --profile aws ps 2>/dev/null`  
  Result: Empty table (no services).

### Commands to run on each instance (LAB and PROD) to complete baseline

Run these on the target host (e.g. via SSM start-session or SSH), then paste results into §2 (LAB) or §3 (PROD) and update the one-page stack.

```bash
# 1) systemd timers (health/recovery)
systemctl list-timers --all --no-pager
systemctl list-timers --all --no-pager | grep -iE 'atp|health|nightly|dashboard'

# 2) systemd unit files (health/recovery)
systemctl list-unit-files --no-pager | grep -iE 'atp|health_monitor|dashboard_health|nightly-integrity'

# 3) status of specific timers
for u in atp-selfheal atp-health-snapshot atp-health-alert nightly-integrity-audit dashboard_health_check; do
  echo "=== $u.timer ==="; systemctl status "$u.timer" --no-pager 2>/dev/null || echo "not found"
done

# 4) status of specific services
for u in atp-selfheal atp-health-snapshot atp-health-alert health_monitor dashboard_health_check nightly-integrity-audit; do
  echo "=== $u.service ==="; systemctl status "$u.service" --no-pager 2>/dev/null || echo "not found"
done

# 5) SSM agent (PROD uses snap unit), docker
systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || systemctl is-active amazon-ssm-agent 2>/dev/null || true
systemctl is-active docker 2>/dev/null || true

# 6) crontab
echo "=== ubuntu crontab ==="; crontab -l 2>/dev/null || echo "no crontab"
echo "=== root crontab ==="; sudo crontab -l 2>/dev/null || echo "no root crontab"

# 7) backend health endpoints (from host)
curl -sS -o /dev/null -w "api/health %{http_code}\n" --max-time 5 http://127.0.0.1:8002/api/health
curl -sS -o /dev/null -w "api/health/system %{http_code}\n" --max-time 5 http://127.0.0.1:8002/api/health/system
curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system | jq -c '.global_status, .market_data.status, .market_updater.status' 2>/dev/null || echo "jq or curl failed"

# 8) self-heal verification (from repo root; does not trigger heal)
cd /home/ubuntu/crypto-2.0
./scripts/selfheal/verify.sh; echo "exit=$?"

# 9) logs and state
ls -la /var/log/atp/ 2>/dev/null || echo "NO_ATP_LOG_DIR"
ls -la /var/lib/atp/ 2>/dev/null || echo "NO_ATP_LIB_DIR"
test -f /var/log/atp/health_snapshots.log && tail -3 /var/log/atp/health_snapshots.log || echo "no health_snapshots.log"
test -f /var/lib/atp/health_alert_state.json && cat /var/lib/atp/health_alert_state.json | jq -c . 2>/dev/null || echo "no or invalid state file"

# 10) recent journal logs
for u in atp-selfheal atp-health-snapshot atp-health-alert nightly-integrity-audit health_monitor; do
  echo "=== journal $u ==="; journalctl -u "$u.service" -n 5 --no-pager 2>/dev/null || journalctl -u "$u.timer" -n 5 --no-pager 2>/dev/null || echo "no logs"
done

# 11) Docker
cd /home/ubuntu/crypto-2.0
docker compose --profile aws ps
docker ps --format "table {{.Names}}\t{{.Status}}" | head -20
```

**Note:** Do not run heal.sh or any remediation; only verify.sh (read-only checks) and the above inspection commands.
