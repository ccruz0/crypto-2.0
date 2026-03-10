# Smoke Check System Health Fix

## Problem

After deploy, the smoke check fails with:
```
system_health: FAIL — degraded: global_status, signal_monitor
```

Liveness passes (HTTP 200) but system_health fails, causing the task to be marked blocked.

## Root Cause

1. **Timing**: After deploy, the backend container restarts. `signal_monitor` and `market_updater` run as background services. They may not have completed a cycle within the 120s initial delay, so `signal_monitor` reports `is_running=False` or `last_cycle_age_minutes=None` (no cycle yet).

2. **Poor diagnostics**: The failure message only listed component names ("degraded: global_status, signal_monitor") without explaining *why* each failed.

## Fixes Implemented

### 1. System health retries

When `system_health` fails, the smoke check now retries up to 3 times with 30s delay between attempts. This gives subsystems time to become ready after a deploy restart.

**Env vars:**
- `SMOKE_CHECK_SYSTEM_HEALTH_RETRIES` (default: 3)
- `SMOKE_CHECK_SYSTEM_HEALTH_RETRY_DELAY_S` (default: 30)

### 2. Improved diagnostics

The failure message now includes per-component reasons, for example:

```
system_health: FAIL (455ms)
  signal_monitor: not running
  market_updater: not running (data age 45min)
```

Instead of:
```
system_health: FAIL — degraded: global_status, signal_monitor
```

**Component reasons:**
- `signal_monitor`: "not running" | "no cycle yet (startup)" | "last cycle Xmin ago (stale)"
- `market_updater`: "not running (data age Xmin)" | "not running"
- `market_data`: "fresh=N stale=M"
- `telegram`: "disabled by env" | "config missing or kill switch"
- `trade_system`: "order_intents table missing"

### 3. Exclude global_status from degraded list

`global_status` is the aggregate; it was incorrectly listed as a "degraded component". It is now excluded from the failed-components list.

## Files Changed

- `backend/app/services/deploy_smoke_check.py`:
  - `_component_reason()` — build human-readable reason per component
  - `check_system_health()` — extract reasons, exclude global_status, return `component_reasons`
  - `run_smoke_check()` — retry system_health when FAIL

## Verification

1. Deploy the changes.
2. Trigger a deploy and run smoke check (or let webhook run it).
3. If it still fails, the message will show the specific reason (e.g. "signal_monitor: not running").
4. If it passes after retry, logs will show: `system_health attempt 1/3 failed (may be startup timing), retrying in 30s`.

## If signal_monitor Still Fails

If `signal_monitor` remains "not running" after retries:

1. **Check backend logs**: `docker logs <backend-container> 2>&1 | grep -i signal_monitor`
2. **Verify startup**: Signal monitor is started in `app.main` on startup. Ensure `DEBUG_DISABLE_SIGNAL_MONITOR` is not set.
3. **Check status file**: `cat /tmp/signal_monitor_status.json` (path from `SIGNAL_MONITOR_STATUS_FILE`).
4. **Increase delay**: Set `SMOKE_CHECK_INITIAL_DELAY_S=180` to wait longer before first check.
