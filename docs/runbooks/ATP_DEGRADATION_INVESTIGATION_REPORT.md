# ATP Degradation & Task-System Delay — Investigation Report

**Date:** 2025-03-21  
**Status:** Root cause identified; mitigations and fix proposed

---

## Executive Summary

| Finding | Detail |
|--------|--------|
| **Root cause** | Backend (Gunicorn) unreachable or overloaded → health checks fail → scheduler cannot run → stuck tasks accumulate → burst of alerts on recovery |
| **ATP degradation ↔ task delay** | **Related.** Both stem from backend unavailability; scheduler runs inside the backend process. |
| **Exact failing component** | Backend service (backend-aws container / Gunicorn workers) |
| **502 Bad Gateway** | nginx upstream (localhost:3000 frontend or localhost:8002 backend) did not respond; most likely backend |

---

## 1. Symptoms Observed

1. OpenClaw / task system silent ~17 minutes, then burst of stuck/re-investigate alerts
2. Telegram Re-investigate works intermittently
3. ATP Control health alert: `API_HEALTH: missing`, `market_data: unknown`, `market_updater: unknown`, `global_status: unknown`
4. Dashboard returned 502 Bad Gateway

---

## 2. Health Pipeline — How API_HEALTH:missing Arises

### 2.1 Flow

```
atp-health-snapshot.timer (every 5 min)
  → health_snapshot_log.sh
    → verify.sh (curl -sS --max-time 5 http://127.0.0.1:8002/api/health)
    → curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system
  → appends JSONL to /var/log/atp/health_snapshots.log

atp-health-alert.timer (every 5 min)
  → health_snapshot_telegram_alert.sh
    → reads last N lines of log
    → streak_fail_3 rule → sends ATP Control Telegram alert
```

### 2.2 When API_HEALTH:missing Occurs

**File:** `scripts/selfheal/verify.sh` (lines 28–29, 55–58)

```bash
health="$(curl_json "$BASE/api/health" || echo '{}')"
...
api_ok="$(echo "$health" | jq -r '.status // empty' 2>/dev/null || true)"
if [ "${api_ok:-}" != "ok" ]; then
  echo "FAIL:API_HEALTH:${api_ok:-missing}"
  exit 4
fi
```

`api_ok` is empty when:

- `curl` fails (connection refused, timeout, non-2xx)
- Backend returns JSON without `.status == "ok"` (e.g. `{}` on error)

**Conclusion:** `FAIL:API_HEALTH:missing` indicates backend at `http://127.0.0.1:8002` was unreachable within 5 seconds.

### 2.3 Why market_data / market_updater / global_status Are "unknown"

**File:** `scripts/diag/health_snapshot_log.sh` (lines 45–46, 56–66)

```bash
health_system="$(curl -sS --max-time 5 "$BASE/api/health/system" 2>/dev/null || echo "{}")"
```

If backend is down, `health_system` becomes `{}`. Then `$sys[0].market_data.status` etc. are null → written as `"unknown"` in the log and in the ATP Control alert.

---

## 3. Stuck Alerts — Real-Time vs Batched

### 3.1 Stuck Detection Is Batched per Scheduler Cycle

**File:** `backend/app/services/agent_scheduler.py` (lines 208–214)

```python
# Stuck task detection and recovery (before preparing next task)
try:
    from app.services.task_health_monitor import check_for_stuck_tasks
    handled = check_for_stuck_tasks()
```

**File:** `backend/app/services/agent_scheduler.py` (lines 586–614)

- Scheduler loop runs `run_agent_scheduler_cycle()` every **300s** (default `AGENT_SCHEDULER_INTERVAL_SECONDS`).

### 3.2 Stuck Alert Cooldown

**File:** `backend/app/services/task_health_monitor.py` (lines 38, 351–357)

```python
ALERT_COOLDOWN_MINUTES = 30
...
send_alert = (
    (last_alert is None or (now_ts - last_alert) >= (ALERT_COOLDOWN_MINUTES * 60))
    and not _recently_failed_reinvestigate(task_id, now_ts)
)
```

- Max one stuck alert per task per 30 minutes.
- Alerts are not queued; they are sent synchronously via `send_claw_message` from `claw_telegram`.

### 3.3 Why a Burst After ~17 Minutes?

1. Backend down or severely overloaded → scheduler does not run (or runs very slowly).
2. Tasks in `in-progress`, `investigating`, `patching`, `testing` exceed stuck thresholds (15/10 min).
3. When backend recovers, the next scheduler cycle:
   - Calls `check_for_stuck_tasks()`
   - Fetches up to 50 tasks, finds all stuck ones
   - For each: `handle_stuck_task()` → if cooldown passed, sends one alert
4. Multiple stuck tasks processed in a single cycle → multiple alerts in a short burst.

**Conclusion:** Alerts are emitted per stuck task during each cycle, not continuously. The “burst” is the scheduler catching up after a period of inactivity.

---

## 4. Re-investigate Intermittency

**File:** `backend/app/services/telegram_commands.py` (lines 6125–6195)

Re-investigate handler:

1. Receives callback `reinvestigate:<task_id>`
2. Calls Notion API to move task to `ready-for-investigation`
3. On success: confirms via Telegram
4. On failure: calls `record_reinvestigate_failed(task_id)` → suppresses stuck alerts for 90 minutes

**Causes of intermittency:**

- Backend down → no callback processing
- Telegram poller only in main backend (`RUN_TELEGRAM_POLLER=true`); canary does not poll
- Notion API timeouts/failures → Notion write fails → reinvestigate appears to “not work”

---

## 5. 502 Bad Gateway — Root Cause

**File:** `nginx/dashboard.conf`

- `/` → `proxy_pass http://localhost:3000` (frontend)
- `/api` → `proxy_pass http://localhost:8002/api` (backend)

502 occurs when nginx cannot get a valid response from upstream (connection refused, timeout, or invalid response).

**Typical cause:** Backend on 8002 not responding (restart, crash, overload, or long-running request blocking workers).

---

## 6. Dependency Chain

```
Backend (Gunicorn 2 workers) ← scheduler loop in-process
        ↓
   /api/health, /api/health/system
        ↓
verify.sh, health_snapshot_log.sh (curl to 127.0.0.1:8002)
        ↓
   FAIL when backend unreachable
```

```
Backend unreachable
  → verify.sh: FAIL:API_HEALTH:missing
  → health_system = {}
  → market_data/market_updater/global_status = unknown
  → ATP Control alert with all unknowns
```

```
Backend unreachable
  → Scheduler not running (in-process)
  → No stuck detection
  → Tasks accumulate as stuck
  → On recovery: one cycle processes many → burst
```

---

## 7. Commands for Runtime Verification

### 7.1 Backend and Health

```bash
cd /home/ubuntu/crypto-2.0

# Backend reachable?
curl -sS --max-time 5 http://127.0.0.1:8002/api/health
# Expect: {"status":"ok","path":"/api/health"}

curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system | jq '.global_status, .market_data.status, .market_updater.status'

# Fast ping (used by healthcheck)
curl -sS --max-time 5 http://127.0.0.1:8002/ping_fast
```

### 7.2 Containers

```bash
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "backend|market|frontend"
```

### 7.3 Health Snapshot Log

```bash
tail -20 /var/log/atp/health_snapshots.log
```

### 7.4 Scheduler Heartbeat

```bash
curl -sS "http://127.0.0.1:8002/api/agent/state" | jq '.scheduler_running, .last_scheduler_cycle, .scheduler_interval_s'
```

### 7.5 Ports

```bash
ss -tlnp | grep -E '3000|8002'
```

### 7.6 Backend Logs

```bash
docker logs --tail 200 automated-trading-platform-backend-aws-1 2>&1 | grep -E "scheduler|health|ERROR|502"
```

---

## 8. Root Cause Summary

| Component | Status | Evidence |
|-----------|--------|----------|
| Backend | **Primary failure** | API_HEALTH:missing when backend unreachable |
| Scheduler | **Consequence** | Runs inside backend; no cycles when backend down |
| Market updater | **Secondary** | Likely OK; "unknown" from empty health JSON when backend down |
| Stuck alerts | **Consequence** | Batched per cycle; burst after backend recovery |
| 502 | **Symptom** | nginx cannot reach backend (or frontend) upstream |

**Root cause:** Backend (backend-aws) becomes unreachable or overloaded. Health scripts and scheduler depend on it, so failures cascade.

---

## 9. Safe Immediate Mitigation

**Action:** Restart backend and verify health.

```bash
cd /home/ubuntu/crypto-2.0
docker compose --profile aws up -d backend-aws --force-recreate
sleep 30
curl -sS --max-time 5 http://127.0.0.1:8002/api/health
curl -sS --max-time 5 http://127.0.0.1:8002/api/health/system | jq '.global_status'
```

If backend is responsive, the next health snapshot (within 5 min) should log PASS and clear the streak.

---

## 10. Proper Fix — Hardening Backend Resilience

### 10.1 Nginx: Align /api/health With verify.sh

**Current:** `location = /api/health` proxies to `/__ping` (returns `{"ok": true}`). External health checks expecting `{"status":"ok"}` will fail.

**File:** `nginx/dashboard.conf` (lines 182–186)

```nginx
# Current
location = /api/health {
    proxy_pass http://localhost:8002/__ping;
    access_log off;
}
```

**Change:** Proxy to the real health endpoint so both internal and external checks get the same format:

```nginx
location = /api/health {
    proxy_pass http://localhost:8002/api/health;
    proxy_connect_timeout 5s;
    proxy_read_timeout 5s;
    access_log off;
}
```

Then reload nginx: `sudo nginx -t && sudo systemctl reload nginx`.

### 10.2 Backend: Dedicated Health Worker (Optional)

Run a minimal health-only process (e.g. single-worker uvicorn on another port) for `/api/health` and `/api/health/system`, so main Gunicorn overload does not block health checks. This is a larger architectural change and can be done later.

### 10.3 Add Scheduler Heartbeat Monitoring

- Expose `last_scheduler_cycle` and `scheduler_interval_s` in a monitoring endpoint.
- Alert when no cycle has run for `2 * interval` (e.g. 10 minutes with default 300s).
- This helps detect scheduler stalls even when `/api/health` still responds.

### 10.4 Reduce Stuck-Alert Burst (Optional)

- Add jitter or rate limiting in `send_claw_message` when sending multiple stuck alerts in one cycle.
- Or consolidate multiple stuck tasks into one summary message when many are stuck.

---

## 11. Evidence With Timestamps

| Timestamp source | Location | Use |
|------------------|----------|-----|
| Scheduler cycle | `agent_scheduler._last_cycle_ts` | Last cycle completion (UTC) |
| Health snapshot | `ts` in `/var/log/atp/health_snapshots.log` | When verify ran |
| Stuck detection | `agent_activity_log` events `stuck_task_detected`, `scheduler_cycle_completed` | Task stuck vs cycle timing |
| Re-investigate | `[TG][EXT_APPROVAL] reinvestigate` in backend logs | When reinvestigate was processed |

**Example correlation:**

```bash
# Last scheduler cycle
curl -sS "http://127.0.0.1:8002/api/agent/state" | jq '.last_scheduler_cycle'

# Last health snapshots
tail -5 /var/log/atp/health_snapshots.log | jq -r '.ts + " " + .verify_label + " " + .severity'

# Agent activity (if table exists)
# SELECT event_type, task_id, created_at FROM agent_activity_log ORDER BY created_at DESC LIMIT 20;
```

---

## 12. Reference Files

| Purpose | File |
|---------|------|
| verify.sh | `scripts/selfheal/verify.sh` |
| health_snapshot_log.sh | `scripts/diag/health_snapshot_log.sh` |
| health_snapshot_telegram_alert.sh | `scripts/diag/health_snapshot_telegram_alert.sh` |
| system_health | `backend/app/services/system_health.py` |
| task_health_monitor | `backend/app/services/task_health_monitor.py` |
| agent_scheduler | `backend/app/services/agent_scheduler.py` |
| claw_telegram | `backend/app/services/claw_telegram.py` |
| nginx config | `nginx/dashboard.conf` |
| Runbook | `docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md` |
