# Alert System Fix - Implementation Summary

## Root Cause Explanation (Plain English)

**The Problem:**
- Many database rows have `alert_enabled=False` because the default value in the SQLAlchemy model is `False`
- When new rows are created or migrated, they default to `False` unless explicitly set to `True`
- The frontend UI shows alerts as enabled (buttons appear enabled/YES), but the database has them as disabled (False)
- The backend signal monitor only processes coins with `alert_enabled=True`, so alerts are blocked even when the UI suggests they should be enabled

**Why This Happens:**
1. Database default is `False` (conservative default - safer to not send alerts by default)
2. Historical rows were created before `alert_enabled` was explicitly set, so they remain `False`
3. No migration was run to normalize existing rows to match user expectations
4. Frontend may show optimistic UI state that doesn't match database reality

**The Fix:**
1. ✅ **Enhanced Logging**: Added startup configuration summary and enhanced blocking logs with source tracking
2. ✅ **Migration Script**: Created migration to set `alert_enabled=True` for all active coins (one-time fix)
3. ✅ **Alert Decision Logging**: Added `[ALERT_ALLOWED]` and `[ALERT_CHECK]` logs to track alert decisions
4. ⏳ **Diagnostic Endpoint**: (To be created) Endpoint to verify alert configuration
5. ⏳ **Database Migration Execution**: (User action required) Run migration on production

---

## Files Changed

### 1. backend/app/services/signal_monitor.py

**Changes:**
- Added `_log_startup_alert_configuration()` method (lines ~1237-1280)
  - Logs alert configuration summary on startup
  - Shows total active coins, enabled count, disabled count
  - Logs per-symbol configuration (first 20 symbols)
  - Format: `[STARTUP_ALERT_CONFIG] symbol=XXX alert_enabled=... source=db`

- Enhanced `monitor_signals()` method (line ~1380)
  - Calls `_log_startup_alert_configuration()` on first run
  - Tracks if startup config has been logged to avoid log spam

- Enhanced BUY alert blocking logs (lines ~2866-2914)
  - Added `[ALERT_CHECK]` log with all flags before blocking
  - Enhanced blocking message to include DB value source
  - Format: `[ALERT_CHECK] symbol=XXX gate=alert_enabled decision=BLOCK reason=ALERT_DISABLED ... source=db`

- Enhanced BUY alert allowed logs (line ~2805)
  - Added `[ALERT_ALLOWED]` log when alert is allowed
  - Format: `[ALERT_ALLOWED] symbol=XXX gate=alert_enabled+buy_alert_enabled decision=ALLOW ... source=db`

- Enhanced SELL alert allowed logs (line ~4862)
  - Added `[ALERT_ALLOWED]` log when alert is allowed
  - Format: `[ALERT_ALLOWED] symbol=XXX gate=alert_enabled+sell_alert_enabled decision=ALLOW ... source=db`

### 2. backend/migrations/enable_alerts_for_all_coins.sql

**Status:** Already exists, needs execution

**Purpose:** Sets `alert_enabled=True` for all active (non-deleted) watchlist items

**Usage:**
```bash
# On AWS (via SSM or SSH)
docker exec -it <postgres_container> psql -U trader -d atp -f /path/to/enable_alerts_for_all_coins.sql

# Or locally
psql -U trader -d atp -f backend/migrations/enable_alerts_for_all_coins.sql
```

---

## Migration/Repair Steps

### Step 1: Execute Database Migration (Required)

**Action:** Run the migration script to set `alert_enabled=True` for all active coins

**Command (AWS via SSM):**
```bash
aws ssm start-session --target <instance-id> --document-name AWS-StartInteractiveCommand --parameters command="docker exec -it postgres_hardened psql -U trader -d atp -f /app/backend/migrations/enable_alerts_for_all_coins.sql"
```

**Command (AWS via SSH):**
```bash
ssh <user>@<host>
docker exec -it postgres_hardened psql -U trader -d atp -f /app/backend/migrations/enable_alerts_for_all_coins.sql
```

**Verification:**
```sql
SELECT 
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE alert_enabled = true) as enabled,
    COUNT(*) FILTER (WHERE alert_enabled = false) as disabled
FROM watchlist_items
WHERE is_deleted = false;
```

Expected: `disabled = 0` (all active rows should have `alert_enabled=true`)

### Step 2: Deploy Code Changes (Required)

**Action:** Deploy the updated `signal_monitor.py` with enhanced logging

**Command:**
```bash
# Standard deployment process
# (depends on your deployment method)
```

**Verification:**
- Check backend logs for `[STARTUP_ALERT_CONFIG]` messages on startup
- Verify enhanced blocking logs appear when alerts are blocked

### Step 3: Verify Alert Configuration (Recommended)

**Action:** Check startup logs to verify alert configuration

**Command:**
```bash
# On AWS
docker logs <backend_container> | grep "STARTUP_ALERT_CONFIG" | tail -30
```

**Expected Output:**
```
[STARTUP_ALERT_CONFIG] total_active_coins=50 alert_enabled_true=50 alert_enabled_false=0
[STARTUP_ALERT_CONFIG] symbol=BTC_USDT alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db
[STARTUP_ALERT_CONFIG] symbol=ETH_USDT alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db
...
```

---

## How to Verify on AWS (Exact Commands)

### 1. Check Database State

```bash
# Connect to database container
docker exec -it postgres_hardened psql -U trader -d atp

# Check alert_enabled values
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled 
FROM watchlist_items 
WHERE is_deleted = false 
ORDER BY symbol 
LIMIT 20;

# Count enabled vs disabled
SELECT 
    COUNT(*) as total_active,
    COUNT(*) FILTER (WHERE alert_enabled = true) as enabled,
    COUNT(*) FILTER (WHERE alert_enabled = false) as disabled
FROM watchlist_items
WHERE is_deleted = false;
```

### 2. Check Backend Startup Logs

```bash
# View startup alert configuration
docker logs <backend_container> 2>&1 | grep "STARTUP_ALERT_CONFIG" | head -30

# Check for any blocking messages
docker logs <backend_container> 2>&1 | grep "BLOQUEADO" | tail -20

# Check for alert allowed messages
docker logs <backend_container> 2>&1 | grep "ALERT_ALLOWED" | tail -20
```

### 3. Check API Response

```bash
# Get alert status for a specific symbol
curl -X GET https://<api_url>/api/dashboard | jq '.[] | select(.symbol == "BTC_USDT") | {symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled}'

# Get all symbols with alert status
curl -X GET https://<api_url>/api/dashboard | jq '.[] | {symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled}'
```

### 4. Trigger Test Alert (Optional)

```bash
# If you have a test endpoint or can trigger a real signal
# Check logs for ALERT_ALLOWED messages
docker logs <backend_container> 2>&1 | grep "ALERT_ALLOWED" | tail -10
```

---

## Expected Log Format

### Startup Configuration
```
[STARTUP_ALERT_CONFIG] total_active_coins=50 alert_enabled_true=50 alert_enabled_false=0
[STARTUP_ALERT_CONFIG] symbol=BTC_USDT alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db
```

### Alert Allowed
```
[ALERT_ALLOWED] symbol=BTC_USDT gate=alert_enabled+buy_alert_enabled decision=ALLOW alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True source=db evaluation_id=xxx
```

### Alert Blocked
```
[ALERT_CHECK] symbol=BTC_USDT gate=alert_enabled decision=BLOCK reason=ALERT_DISABLED alert_enabled=False buy_alert_enabled=False sell_alert_enabled=False source=db evaluation_id=xxx
🚫 BLOQUEADO: BTC_USDT - Las alertas están deshabilitadas para este símbolo (alert_enabled=False). ... Valor leído desde DB: alert_enabled=False
```

---

## Long-Term Robustness (Future Improvements)

### 1. Database Constraints
- Add NOT NULL constraint to `alert_enabled` (if not already present)
- Ensure no NULL values exist (migration to set NULL → False)

### 2. Diagnostic Endpoint (To Be Created)
- Endpoint: `GET /api/dashboard/alert-status`
- Returns: Per-symbol alert flags from DB
- Use: Frontend diagnostic tool to compare UI state with DB state

### 3. Frontend Validation
- Compare UI state with API response on load
- Log discrepancies
- Auto-sync UI state from API (already done, but can be enhanced)

### 4. Startup Health Check
- Fail fast if alert configuration is inconsistent
- Alert admin if too many coins have `alert_enabled=False` unexpectedly

---

## Notes

- **Migration is one-time only**: After running the migration, all active coins will have `alert_enabled=True`
- **User can still disable alerts**: The migration sets all to True, but users can still toggle them to False via the UI
- **Enhanced logging is permanent**: The new logging will help diagnose future issues
- **No breaking changes**: All changes are additive (logging) or one-time (migration)

---

## Next Steps

1. ✅ Code changes implemented (enhanced logging)
2. ⏳ Execute database migration on production
3. ⏳ Deploy code changes to production
4. ⏳ Verify startup logs show correct configuration
5. ⏳ Monitor alert sending to confirm alerts are not blocked
6. ⏳ (Optional) Create diagnostic endpoint for future troubleshooting
