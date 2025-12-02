# Full Runtime Health Audit Report

**Date:** 2025-12-02  
**Auditor:** Automated Health Check System  
**Environment:** AWS Production (hilovivo-aws)

---

## Executive Summary

This audit was performed to investigate why SignalMonitorService appeared to have stopped producing alerts. The investigation revealed that:

✅ **SignalMonitorService IS running and processing symbols**  
✅ **Alerts ARE being sent** (last alert ~9 minutes before audit)  
⚠️ **Backend container shows "unhealthy" status** but API endpoints are responding  
✅ **All critical API endpoints are functional**

---

## 1. Container Health Status

### Container Status Table

| Container Name | Status | Notes |
|---------------|--------|-------|
| `automated-trading-platform-backend-1` | **Up 26 minutes (unhealthy)** | API responding, but health check failing |
| `automated-trading-platform-frontend-aws-1` | **Up 2 hours (healthy)** | ✅ Healthy |
| `automated-trading-platform-market-updater-1` | **Up 37 seconds (health: starting)** | Starting up |

### Findings

- **Backend container is marked "unhealthy"** but continues to serve API requests
- All containers are running (none crashed or exited)
- Frontend is healthy
- Market updater was recently restarted

**Action Required:** Investigate why backend health check is failing despite API being functional.

---

## 2. Backend API Health Endpoints

### Test Results

| Endpoint | Status | Response |
|----------|--------|----------|
| `GET /api/health` | ✅ **PASS** | `{"status":"ok","path":"/api/health"}` |
| `GET /api/dashboard/snapshot` | ✅ **PASS** | Returns portfolio data with balances |
| `GET /api/monitoring/summary` | ✅ **PASS** | Returns monitoring summary with scheduler_ticks=0 |

### Findings

- All critical API endpoints respond with HTTP 200
- JSON responses are valid
- Dashboard snapshot contains expected data structure
- Monitoring summary shows `scheduler_ticks=0` (may indicate scheduler not running or not reporting)

**Action Required:** Investigate why `scheduler_ticks=0` in monitoring summary.

---

## 3. Scheduler and SignalMonitorService Status

### Code Analysis

**Location:** `backend/app/main.py` lines 199-209

```python
if not DEBUG_DISABLE_SIGNAL_MONITOR:
    try:
        logger.info("🔧 Starting Signal monitor service...")
        from app.services.signal_monitor import signal_monitor_service
        loop = asyncio.get_running_loop()
        signal_monitor_service.start_background(loop)
        logger.info("✅ Signal monitor service start() scheduled")
    except Exception as e:
        logger.error(f"❌ Failed to start signal monitor: {e}", exc_info=True)
```

**Feature Flag:** `DEBUG_DISABLE_SIGNAL_MONITOR = False` (✅ Enabled)

### Log Evidence

From recent logs (`/tmp/backend_tail_4000.log`):

- ✅ **SignalMonitorService IS running**
- ✅ **DEBUG_SIGNAL_MONITOR logs appear regularly** (processing symbols every ~30 seconds)
- ✅ **Last cycle completed:** `SignalMonitorService cycle #1 completed. Next check in 30s` (at 06:10:16)

### Recent SignalMonitor Activity

```
2025-12-02 06:10:16,833 [INFO] SignalMonitorService cycle #1 completed. Next check in 30s
2025-12-02 06:09:58,274 [INFO] [DEBUG_SIGNAL_MONITOR] symbol=AAVE_USDT | preset=swing-Conservative | ...
2025-12-02 06:09:37,962 [INFO] [DEBUG_SIGNAL_MONITOR] symbol=APT_USDT | preset=swing-Conservative | ...
2025-12-02 06:09:11,479 [INFO] [DEBUG_SIGNAL_MONITOR] symbol=NEAR_USDT | preset=swing-Conservative | ...
```

### Findings

- ✅ SignalMonitorService is registered and running
- ✅ No feature flags are disabling it
- ✅ Service is processing symbols in cycles
- ✅ Debug logging is active

**No Action Required** - SignalMonitorService is functioning correctly.

---

## 4. SignalMonitor Logs Analysis

### Log Search Results

**Search Pattern:** `SignalMonitorService|DEBUG_SIGNAL_MONITOR|_run_signal_monitor`

**Results:**
- ✅ **Found 20+ DEBUG_SIGNAL_MONITOR entries** in last 4000 log lines
- ✅ **SignalMonitorService cycle completion logged**
- ✅ **No tracebacks or exceptions** related to SignalMonitor

### Recent Activity Timeline

- **06:10:16** - SignalMonitorService cycle #1 completed
- **06:09:58** - Processing AAVE_USDT
- **06:09:37** - Processing APT_USDT
- **06:09:11** - Processing NEAR_USDT
- **06:08:51** - Processing SUI_USDT
- **06:08:25** - Processing AKT_USDT
- **06:08:07** - Processing TON_USDT

### Findings

- ✅ SignalMonitorService is actively processing symbols
- ✅ Logs appear every ~30 seconds (matching monitor_interval)
- ✅ No errors or crashes detected
- ⚠️ All recent decisions are `WAIT` (no BUY/SELL signals detected)

**No Action Required** - SignalMonitorService is logging correctly.

---

## 5. Alert Pipeline End-to-End Check

### Recent Alert Activity

**Last Alert Timestamp:** `2025-12-02T06:01:40.045017+00:00` (ALGO_USDT BUY signal)

**Alert Details:**
- Symbol: ALGO_USDT
- Type: BUY SIGNAL
- Status: SENT (not blocked)
- Throttle: `cooldown OK (882.42m >= 5.00m)`

### Alert Emission Logic Verification

**Code Location:** `backend/app/services/signal_monitor.py` lines 1050-1128

**Flow:**
1. ✅ `calculate_trading_signals()` called for each symbol
2. ✅ `should_emit_signal()` checks throttle rules
3. ✅ `_send_buy_alert_and_order()` called when conditions met
4. ✅ `telegram_notifier.send_buy_signal()` sends alert
5. ✅ Alert recorded in Monitoring via `add_telegram_message()`

### Recent BUY Signals Detected

From logs, LDO_USD had BUY signals at:
- **06:09:30-06:09:33** - Multiple `decision=BUY | buy_signal=True` entries

However, no corresponding alert emission logs found for these signals in the analyzed timeframe.

### Findings

- ✅ Alert pipeline code is intact
- ✅ Recent alerts were sent successfully (ALGO_USDT at 06:01:40)
- ⚠️ **Gap:** LDO_USD had BUY signals at 06:09:30 but no alert emission logs found
- ⚠️ **Possible causes:**
  - Throttle blocking (cooldown period)
  - `alert_enabled=False` or `buy_alert_enabled=False` for LDO_USD
  - Alert sent but not logged (unlikely)

**Action Required:** Investigate why LDO_USD BUY signals at 06:09:30 did not trigger alerts.

---

## 6. Monitoring API Endpoints

### Test Results

| Endpoint | Status | Notes |
|----------|--------|-------|
| `GET /api/monitoring/telegram-messages` | ✅ **PASS** | Returns recent alerts |
| `GET /api/monitoring/summary` | ✅ **PASS** | Returns monitoring summary |

### Recent Messages

Last 5 messages from Monitoring API:
1. **06:01:40** - ALGO_USDT BUY SIGNAL (SENT)
2. **06:01:39** - ALGO_USDT BUY SIGNAL (formatted)
3. **06:01:24** - ALGO_USDT BUY SIGNAL (SENT)
4. **06:01:23** - ALGO_USDT BUY SIGNAL (formatted)
5. **06:00:51** - LDO_USD BUY SIGNAL (SENT)

### Findings

- ✅ Monitoring API is functional
- ✅ Recent alerts are being recorded
- ⚠️ **Gap:** Last alert was ~9 minutes before audit (06:01:40 vs audit time ~06:10)
- ⚠️ No alerts for LDO_USD BUY signals detected at 06:09:30

**Action Required:** Investigate why alerts are not being sent for all BUY signals.

---

## 7. Health Check Script Results

### Script Created

- ✅ `backend/scripts/check_runtime_health.py` - Python health check script
- ✅ `scripts/check_runtime_health_aws.sh` - AWS wrapper script

### Usage

From Mac:
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/check_runtime_health_aws.sh
```

---

## 8. Summary and Next Steps

### ✅ What is Healthy

1. **SignalMonitorService is running** - Processing symbols every 30 seconds
2. **API endpoints are functional** - All critical endpoints respond correctly
3. **Alert pipeline code is intact** - No blocking logic issues found
4. **Recent alerts were sent** - ALGO_USDT alerts at 06:01:40
5. **Monitoring API is working** - Recent messages are recorded

### ⚠️ What Needs Investigation

1. **Backend container health check failing** - Container marked "unhealthy" but API works
2. **Scheduler ticks = 0** - Monitoring summary shows no scheduler activity
3. **Alert gap for LDO_USD** - BUY signals at 06:09:30 did not trigger alerts
4. **No recent alerts** - Last alert was ~9 minutes before audit (may be normal if no BUY conditions)

### 🔧 Concrete Next Actions

1. **Investigate backend health check:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/aws_backend_logs.sh --tail 200 | grep -i "health\|unhealthy"
   ```

2. **Check why LDO_USD alerts didn't trigger:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/aws_backend_logs.sh --tail 1000 | grep -E "LDO_USD.*alert|LDO_USD.*throttle|LDO_USD.*buy_alert_enabled"
   ```

3. **Monitor SignalMonitor logs in real-time:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/aws_backend_logs.sh --tail 200 -f | grep -E "DEBUG_SIGNAL_MONITOR|ALERT_EMIT_FINAL|SignalMonitorService cycle"
   ```

4. **Verify scheduler is running:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/aws_backend_logs.sh --tail 500 | grep -E "SCHEDULER|scheduler.*started|run_scheduler"
   ```

---

## 9. Current Run Result

**Health Check Script Status:**

The health check script (`backend/scripts/check_runtime_health.py`) has been created locally but needs to be deployed to AWS before it can be run. The script will be available after the next backend deployment.

**Manual Health Check Results (from this audit):**

✅ API Health: PASS  
✅ Dashboard Snapshot: PASS  
✅ Monitoring Summary: PASS  
⚠️ Scheduler Ticks: 0 (needs investigation)  
✅ Recent Alerts: Found (last alert 9 minutes ago)

---

## 10. Commands for Future Monitoring

### Quick Health Check
```bash
# Note: Script needs to be deployed to AWS first
cd /Users/carloscruz/automated-trading-platform
bash scripts/check_runtime_health_aws.sh
```

### SignalMonitor Logs
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 200 | grep -E "DEBUG_SIGNAL_MONITOR|SignalMonitorService cycle|ALERT_EMIT_FINAL"
```

### Recent Alerts
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 1000 | grep -E "ALERT_EMIT_FINAL|send_buy_signal|send_sell_signal" | tail -20
```

### Container Status
```bash
sh -c "ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker ps --format \"table {{.Names}}\t{{.Status}}\"'"
```

---

**Report Generated:** 2025-12-02  
**Next Review:** When alerts stop appearing or backend health check fails

