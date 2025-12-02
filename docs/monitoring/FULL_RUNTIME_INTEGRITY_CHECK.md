# FULL RUNTIME INTEGRITY CHECK – AWS ONLY

**Date:** 2025-12-02  
**Purpose:** End-to-end validation of AWS production runtime integrity

---

## Context

**AWS is the ONLY production runtime** (trading + alerts).  
**Mac is only for development and SSH-based diagnostics.**

This workflow validates the complete path from signals → monitor → alerts → Telegram → Crypto.com → containers to ensure the entire system is functioning correctly.

---

## How to Run

From your Mac:

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/full_runtime_integrity_check_aws.sh
```

This script runs all checks sequentially and prints a clear summary.

---

## Step-by-Step Checks

### a) Check Backend Health Summary

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/check_runtime_health_aws.sh
```

**What to verify:**
- ✅ API responds with HTTP 200
- ✅ `scheduler_ticks > 0` (scheduler is running)
- ✅ `signal_monitor_ticks > 0` (SignalMonitorService is active)
- ✅ `last_update_seconds_ago < 60` (recent activity)

**Expected output:** All checks should show ✅ PASSED. If any check fails, investigate the specific endpoint or service.

---

### b) Check SignalMonitorService Cycles

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "DEBUG_SIGNAL_MONITOR|SignalMonitorService|_run_signal_monitor" | tail -50
```

**What to verify:**
- ✅ You should see cycles every ~30 seconds
- ✅ Log entries show `[DEBUG_SIGNAL_MONITOR]` with symbol processing
- ✅ No gaps longer than 60 seconds between cycles

**Expected output:** Regular log entries showing SignalMonitorService processing symbols. If no logs appear, SignalMonitorService may not be running.

---

### c) Check Strategy Decisions (BUY/SELL)

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "DEBUG_STRATEGY_FINAL" | tail -40
```

**What to verify:**
- ✅ Strategy decisions are being calculated
- ✅ `decision=BUY` or `decision=SELL` entries appear when conditions are met
- ⚠️ **If there are BUY decisions but no alerts later, there is a problem in the alert pipeline**

**Expected output:** Recent strategy decision logs showing which symbols have BUY/SELL/WAIT decisions. If you see BUY decisions but no corresponding alerts in step (d), investigate the alert pipeline.

---

### d) Check Alerts Being Emitted

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "ALERT_EMIT_FINAL|send_buy_signal|send_sell_signal" | tail -40
```

**What to verify:**
- ✅ `[ALERT_EMIT_FINAL]` entries appear when alerts are sent
- ✅ `send_buy_signal` or `send_sell_signal` entries show alert dispatch
- ✅ Status should be `success` (not `blocked` or `failed`)

**Expected output:** Final alert events here when conditions are met. If BUY decisions exist (from step c) but no alerts appear here, the alert pipeline is blocked or broken.

---

### e) Check Throttled Alerts

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "ALERT_THROTTLED" | tail -40
```

**What to verify:**
- ✅ Throttled alerts show explicit reasons (e.g., "cooldown", "price change too small")
- ⚠️ If many alerts are throttled, verify throttle rules are appropriate
- ⚠️ If alerts are throttled when they shouldn't be, check throttle logic

**Expected output:** Throttled alerts are normal when:
- Same-side alert was sent recently (< 5 minutes if trade_enabled)
- Price change is below threshold
- Cooldown period is active

If alerts are being throttled incorrectly, review throttle rules in `signal_monitor.py`.

---

### f) Check Errors and Exceptions

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E "Traceback|Exception|ERROR" | tail -40
```

**What to verify:**
- ✅ No unexpected errors or exceptions
- ⚠️ Expected errors (e.g., temporary API failures) are logged but don't crash the system
- ❌ **Any non-expected error should be investigated before trusting the system**

**Expected output:** Minimal or no errors. If you see repeated exceptions or tracebacks, investigate the root cause immediately.

---

### g) Check Container Health on AWS

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws "cd automated-trading-platform && docker ps --format '{{.Names}} {{.Status}}'"
```

**What to verify:**
- ✅ Backend container status is "Up" and "healthy"
- ❌ **Backend must NOT be "unhealthy"**
- ✅ All required containers are running (backend, frontend, db, etc.)

**If backend is unhealthy:**
```bash
ssh hilovivo-aws "cd automated-trading-platform && docker restart automated-trading-platform-backend-1"
```

Wait 2-3 minutes, then re-run the health check.

**Expected output:** All containers show "Up" status. Backend should be "healthy", not "unhealthy".

---

### h) Check Crypto.com Auth / Proxy

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 400 | grep -E "CRYPTO_AUTH_DIAG|Proxy authentication error|API credentials not configured"
```

**What to verify:**
- ✅ "Successfully retrieved ... via proxy" = OK
- ✅ No repeated proxy authentication errors
- ❌ "API credentials not configured" = investigate credentials
- ❌ Repeated proxy failures = investigate VPN/proxy/credentials

**Expected output:** Successful proxy connections. If you see authentication errors or "credentials not configured", check:
- VPN connection (gluetun container)
- API credentials in environment variables
- Proxy configuration

---

### i) Check Telegram 409 Status

**Command:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 400 | grep -E "telegram|409" | tail -40
```

**What to verify:**
- ⚠️ 409 conflicts can be normal if another webhook or client is active
- ✅ **It should NOT block outgoing alert messages**
- ✅ Outgoing alerts should still be sent even if 409 appears for incoming commands

**Expected output:** Minimal or no 409 errors. If 409 appears, it usually means:
- Another instance (local dev, old server) is using the same bot token
- **FIX:** Ensure only AWS backend uses the bot token

409 should not prevent outgoing alerts from being sent.

---

## Expected Healthy Result

A healthy system should show:

- ✅ **Backend health summary OK** (all endpoints responding)
- ✅ **Signal monitor ticks increasing** (regular cycles every ~30 seconds)
- ✅ **Strategy decisions present** (BUY/SELL/WAIT decisions being calculated)
- ✅ **ALERT_EMIT_FINAL present** when BUY/SELL decisions exist and throttle allows
- ✅ **No critical errors** (minimal or no exceptions/tracebacks)
- ✅ **Containers healthy** (all containers "Up" and backend "healthy")
- ✅ **Crypto.com responding correctly** (proxy connections successful)
- ✅ **Telegram not blocking outgoing alerts** (409 may appear but doesn't block alerts)

---

## Example Output

See the output from a real run of `scripts/full_runtime_integrity_check_aws.sh` below:

```
==============================
 FULL RUNTIME INTEGRITY CHECK 
==============================

[1] Backend health summary
---------------------------
❌ Backend health check FAILED

[2] SignalMonitor cycles (last 50 lines)
----------------------------------------
[DEBUG_SIGNAL_MONITOR] symbol=LDO_USD | decision=WAIT | buy_signal=False | ...
⚠️  SignalMonitor logs found but no cycle completion messages

[3] Strategy decisions (last 40 DEBUG_STRATEGY_FINAL)
------------------------------------------------------
[DEBUG_STRATEGY_FINAL] symbol=LDO_USD | decision=BUY | buy_signal=True | ...
✅ Strategy decisions found (BUY: 1, SELL: 0)

[4] Alert emissions (ALERT_EMIT_FINAL / send_*_signal)
-------------------------------------------------------
⚠️  No alert emission logs found (may be normal if no BUY/SELL signals)

[5] Throttled alerts (ALERT_THROTTLED)
---------------------------------------
✅ No throttled alerts found (normal if no alerts were throttled)

[6] Recent errors / exceptions
-----------------------------
✅ No recent errors/exceptions found

[7] Docker container status (AWS)
----------------------------------
automated-trading-platform-backend-1 Up About an hour (unhealthy)
automated-trading-platform-frontend-aws-1 Up 3 hours (healthy)
❌ Backend container is UNHEALTHY

[8] Crypto.com auth / proxy status (last 400 log lines)
--------------------------------------------------------
Proxy authentication error while fetching trigger orders: Authentication failure
API credentials not configured. Returning empty trigger orders.
❌ API credentials not configured - investigate credentials

[9] Telegram status (including 409 conflicts)
----------------------------------------------
[TG] getUpdates conflict (409). Another webhook or polling client is active.
⚠️  Telegram 409 conflicts detected (7) - ensure only AWS backend uses bot token

========== CHECK COMPLETE ==========

Summary:
  ✅ Passed: 4
  ⚠️  Warnings: 3
  ❌ Failed: 2

❌ INTEGRITY CHECK FAILED - Investigate failed checks above
```

**Interpretation:**
- ✅ SignalMonitorService is running and processing symbols
- ✅ Strategy decisions are being calculated (LDO_USD had BUY decision)
- ⚠️ No alerts emitted despite BUY decision (investigate alert pipeline)
- ✅ No critical errors or exceptions
- ❌ Backend container is unhealthy (investigate health check endpoint)
- ❌ Crypto.com API credentials not configured (fix credentials)
- ⚠️ Telegram 409 conflicts present (ensure only AWS backend uses bot token)

---

---

## When to Use This Check

Run this integrity check when:

- **Alerts stop appearing** in Monitoring → Telegram Messages
- **Strange gaps** in SignalMonitor cycles (no logs for > 2 minutes)
- **Backend shows unhealthy** status in Docker
- **No BUY/SELL decisions** are being calculated
- **After deployments** to verify everything is working
- **After incidents** to diagnose root causes
- **Periodic health audits** (e.g., daily or weekly)

---

## Troubleshooting

### Telegram 409 Conflicts

**Symptom:** Logs show `[TG] getUpdates conflict (409). Another webhook or polling client is active.`

**Cause:** Another instance (local dev, old server) is using the same bot token.

**Fix:**
1. Stop any local backend instances running Telegram bot
2. Check for old servers still using the bot token
3. Ensure only AWS backend uses the bot token
4. Restart AWS backend: `ssh hilovivo-aws "cd automated-trading-platform && docker restart automated-trading-platform-backend-1"`

**Note:** 409 conflicts should NOT block outgoing alerts. If alerts are not being sent, investigate the alert pipeline separately.

---

### Proxy Authentication Errors

**Symptom:** Logs show `Proxy authentication error` or `API credentials not configured`.

**Cause:** VPN/proxy connection issues or missing API credentials.

**Fix:**
1. Check gluetun container is running: `ssh hilovivo-aws "docker ps | grep gluetun"`
2. Verify VPN credentials in environment variables
3. Check API credentials are set in `.env.aws` or container environment
4. Restart gluetun if needed: `ssh hilovivo-aws "cd automated-trading-platform && docker restart gluetun"`

---

### Child Process Died (Uvicorn)

**Symptom:** Logs show `Child process [XX] died` repeatedly.

**Cause:** Backend process is crashing due to unhandled exceptions.

**Fix:**
1. Check recent errors: `bash scripts/aws_backend_logs.sh --tail 5000 | grep -E "Traceback|Exception" | tail -20`
2. Identify the root cause from the traceback
3. Fix the code issue
4. Restart backend: `ssh hilovivo-aws "cd automated-trading-platform && docker restart automated-trading-platform-backend-1"`

---

### SignalMonitor Not Running

**Symptom:** No `DEBUG_SIGNAL_MONITOR` logs appear for > 2 minutes.

**Cause:** SignalMonitorService is not starting or has crashed.

**Fix:**
1. Check if `DEBUG_DISABLE_SIGNAL_MONITOR` is set to `True` in `backend/app/main.py`
2. Check for startup errors: `bash scripts/aws_backend_logs.sh --tail 1000 | grep -i "signal.*monitor\|failed.*start"`
3. Verify scheduler is running: Check `scheduler_ticks > 0` in monitoring summary
4. Restart backend if needed

---

### Backend Container Unhealthy

**Symptom:** Docker shows backend container as "unhealthy".

**Cause:** Health check endpoint is failing or timing out.

**Fix:**
1. Check health endpoint manually: `ssh hilovivo-aws "curl http://localhost:8002/api/health"`
2. Check backend logs for errors: `bash scripts/aws_backend_logs.sh --tail 200`
3. If API is responding but health check fails, check health check configuration in `docker-compose.yml`
4. Restart backend: `ssh hilovivo-aws "cd automated-trading-platform && docker restart automated-trading-platform-backend-1"`

---

### No Alerts Despite BUY Decisions

**Symptom:** `DEBUG_STRATEGY_FINAL` shows `decision=BUY` but no `ALERT_EMIT_FINAL` appears.

**Cause:** Alert pipeline is blocked (throttle, alert flags, or logic error).

**Fix:**
1. Check alert flags: Verify `alert_enabled=true` and `buy_alert_enabled=true` in database
2. Check throttle logs: `bash scripts/aws_backend_logs.sh --tail 2000 | grep "ALERT_THROTTLED"`
3. Check for blocking logic: `bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "BLOQUEADO|blocked|send_buy_signal verification"`
4. Review `signal_monitor.py` alert logic for unintended blocking conditions

---

### No Strategy Decisions

**Symptom:** No `DEBUG_STRATEGY_FINAL` logs appear.

**Cause:** Strategy calculation is not running or failing silently.

**Fix:**
1. Check if SignalMonitor is running (see "SignalMonitor Not Running" above)
2. Check for strategy calculation errors: `bash scripts/aws_backend_logs.sh --tail 2000 | grep -i "strategy\|calculate_trading_signals"`
3. Verify market data is available: Check `/api/market/top-coins-data` endpoint
4. Check database connectivity: Verify postgres container is healthy

---

## References

- `scripts/full_runtime_integrity_check_aws.sh` - Main integrity check script
- `scripts/check_runtime_health_aws.sh` - Backend health check
- `scripts/aws_backend_logs.sh` - Backend log viewer
- `docs/FULL_RUNTIME_HEALTH_AUDIT.md` - Previous health audit report
- `docs/monitoring/business_rules_canonical.md` - Business rules reference

