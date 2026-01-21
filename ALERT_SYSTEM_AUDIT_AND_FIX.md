# Alert System End-to-End Audit and Fix

## Problem Statement

Telegram daily summaries are sent, but BUY/SELL alerts are not, even though:
- The dashboard shows Alerts = YES for all coins (UI buttons appear enabled)
- The database contains rows with `alert_enabled=False`
- Backend logs show: `🚫 BLOQUEADO: <SYMBOL> - Las alertas están deshabilitadas (alert_enabled=False)`

This indicates a state mismatch between:
- UI / frontend configuration
- Backend runtime logic  
- Database watchlist configuration
- Alert emission logic

---

## Phase 1: Source of Truth Mapping

### Flow: UI toggle → API → DB → backend runtime → signal monitor → alert emitter

1. **Frontend UI (WatchlistTab.tsx)**
   - Location: `frontend/src/app/components/tabs/WatchlistTab.tsx:1397`
   - Toggle buttons: M (master), B (buy), S (sell)
   - State: `coinAlertStatus`, `coinBuyAlertStatus`, `coinSellAlertStatus`
   - Updates via: `handleAlertToggle()` → `updateWatchlistAlert()` / `updateBuyAlert()` / `updateSellAlert()`

2. **API Endpoints (routes_market.py)**
   - `PUT /watchlist/{symbol}/alert` (line 1317): Updates `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
   - `PUT /watchlist/{symbol}/buy-alert` (line 1375): Updates `buy_alert_enabled`
   - `PUT /watchlist/{symbol}/sell-alert` (line 1435): Updates `sell_alert_enabled`

3. **Database Table (watchlist_items)**
   - Schema: `backend/app/models/watchlist.py:28`
   - Columns: `alert_enabled` (Boolean, default=False), `buy_alert_enabled` (Boolean, default=False), `sell_alert_enabled` (Boolean, default=False)
   - Default value: **False** (this is the root cause)

4. **Backend Signal Monitor (signal_monitor.py)**
   - Filter: `_fetch_watchlist_items_sync()` (line 1274) - Only processes items with `alert_enabled = true`
   - Blocking check: `_check_signal_for_coin_sync()` (line 2866) - Blocks alerts if `alert_enabled=False`
   - Uses: `watchlist_items` table (NOT `watchlist_master`)

5. **Alert Emitter (alert_emitter.py)**
   - Called AFTER signal monitor validates `alert_enabled=True`
   - Sends via: `telegram_notifier.send_buy_signal()` / `send_sell_signal()`

### Key Finding: Database Default Value

**Root Cause**: `alert_enabled` column defaults to `False` in the model (line 28 of watchlist.py), meaning:
- New rows created without explicit value = `False`
- Historical rows migrated before explicit setting = `False`
- No migration was run to normalize existing rows to `True`

---

## Phase 2: Discrepancy Analysis

### Why Dashboard Shows YES but Backend Logs Show False

**Possible Explanations:**

1. **Frontend State Not Synced with DB**
   - Frontend initializes state from API, but if API returns stale/incorrect values, UI shows wrong state
   - Location: `frontend/src/app/page.tsx:4244-4262` - Initializes from `getTopCoins()` response
   - If API returns `alert_enabled=True` but DB has `False`, UI shows YES but backend uses False

2. **Database Has alert_enabled=False**
   - Many existing rows have `alert_enabled=False` (default value)
   - User toggles UI to YES, but API update fails silently or doesn't persist
   - UI shows optimistic update, but DB remains False

3. **Frontend Reading Wrong Field**
   - UI might be reading `trade_enabled` instead of `alert_enabled`
   - Or UI shows button state but not actual DB value

4. **API Returns Default True But DB Has False**
   - Serialization layer might be applying defaults
   - Location: `backend/app/api/routes_dashboard.py:118` - Returns `item.alert_enabled` directly (no defaults)

### Investigation Needed

Check actual DB values vs API response vs UI state:
- Query DB: `SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled FROM watchlist_items WHERE is_deleted = false;`
- Check API: `GET /api/dashboard` - Verify returned `alert_enabled` values
- Check UI: Browser console - Verify `coinAlertStatus` state

---

## Phase 3: Short-Term Fix

### Immediate Corrective Actions

1. **Database Migration: Set alert_enabled=True for All Active Rows**
   - File: `backend/migrations/enable_alerts_for_all_coins.sql` (already exists)
   - Action: Execute migration to set `alert_enabled=True` for all `is_deleted=false` rows
   - This aligns DB with UI expectation (all coins enabled)

2. **Backend Startup Logging**
   - Add startup log showing per-symbol alert configuration
   - Location: Signal monitor initialization
   - Log format: `[STARTUP] symbol=XXX alert_enabled=True buy_alert_enabled=True sell_alert_enabled=True`

3. **Enhanced Blocking Logs**
   - Current log: `🚫 BLOQUEADO: {symbol} - Las alertas están deshabilitadas (alert_enabled=False)`
   - Add: Source of value (DB query, cached, default)
   - Add: When was it last updated
   - Add: Suggested fix (run migration, check UI toggle)

---

## Phase 4: Long-Term Robust Fix

### Make This Impossible to Break Again

1. **Database Constraints**
   - **DO NOT** change default to `True` (breaks explicit False intent)
   - Instead: Add CHECK constraint ensuring NULL values are explicitly set
   - Add migration to set NULL → False for historical rows
   - Add comment: "NULL values not allowed - use False to disable"

2. **Single Source of Truth**
   - **Database**: `watchlist_items.alert_enabled` is the ONLY source of truth
   - **Frontend**: Always reads from API, no localStorage defaults
   - **Backend**: Always queries DB (no caching of alert_enabled)
   - **Signal Monitor**: Always refreshes from DB before checking

3. **Backend Validation**
   - On alert send attempt, log ALL flags: `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
   - Log format: `[ALERT_CHECK] symbol=XXX alert_enabled={value} buy_alert_enabled={value} sell_alert_enabled={value} source=db`
   - If alert blocked, log reason_code: `ALERT_DISABLED`, `SIDE_DISABLED`, etc.

4. **Startup Configuration Summary**
   - On signal monitor startup, query all active symbols
   - Log summary: `[STARTUP_ALERT_CONFIG] total_coins={N} enabled={N} disabled={N}`
   - Log per-symbol: `[STARTUP_ALERT_CONFIG] symbol=XXX alert_enabled={value}`

5. **Frontend-Backend Sync Verification**
   - Add diagnostic endpoint: `GET /api/dashboard/alert-status`
   - Returns: Per-symbol alert flags from DB
   - Frontend can compare with local state and log discrepancies

6. **Shared Telegram Gate**
   - Daily summaries and trade alerts use same gate (alert_enabled check)
   - Exception: Daily summaries might intentionally bypass alert_enabled
   - Document: Which alerts respect alert_enabled, which don't

---

## Phase 5: Validation

### Tests and Verification Scripts

1. **Database State Check Script**
   ```sql
   SELECT 
       symbol,
       alert_enabled,
       buy_alert_enabled,
       sell_alert_enabled,
       is_deleted
   FROM watchlist_items
   WHERE is_deleted = false
   ORDER BY symbol;
   ```

2. **API Response Verification**
   ```bash
   curl -X GET http://localhost:8000/api/dashboard | jq '.[] | {symbol: .symbol, alert_enabled: .alert_enabled, buy_alert_enabled: .buy_alert_enabled, sell_alert_enabled: .sell_alert_enabled}'
   ```

3. **Backend Log Verification**
   - After fix, trigger a BUY signal
   - Check logs for: `ALERT_ALLOWED symbol=XXX alert_enabled=True source=db`
   - Verify no blocking messages for enabled coins

4. **End-to-End Test Script**
   - Enable alerts for all symbols (via API)
   - Trigger fake BUY signal (via test endpoint)
   - Verify: Telegram send attempt logged
   - Verify: DB row inserted with SENT status
   - Verify: No blocking messages

---

## Implementation Plan

### Step 1: Execute Migration (Short-Term Fix)
- Run: `backend/migrations/enable_alerts_for_all_coins.sql`
- Verify: All active rows have `alert_enabled=True`

### Step 2: Add Enhanced Logging (Short-Term Fix)
- Update: `backend/app/services/signal_monitor.py`
- Add: Startup configuration summary
- Add: Enhanced blocking logs with source

### Step 3: Add Database Constraints (Long-Term Fix)
- Create: Migration to ensure no NULL values
- Add: CHECK constraint (if supported)
- Add: Default explicit False (keep as-is, but ensure no NULLs)

### Step 4: Add Validation Endpoint (Long-Term Fix)
- Create: `GET /api/dashboard/alert-status`
- Returns: Per-symbol alert flags from DB
- Use: Frontend diagnostic tool

### Step 5: Test and Verify
- Run: Database state check
- Run: API response verification
- Run: Backend log verification
- Run: End-to-end test script

---

## Files to Modify

1. **backend/app/services/signal_monitor.py**
   - Add startup configuration summary logging
   - Enhance blocking log messages
   - Add source tracking (DB query timestamp)

2. **backend/migrations/enable_alerts_for_all_coins.sql**
   - Already exists, needs execution
   - Add verification queries

3. **backend/app/api/routes_dashboard.py** (optional)
   - Add diagnostic endpoint: `GET /api/dashboard/alert-status`

4. **Documentation**
   - Document: Single source of truth (DB)
   - Document: Which alerts respect alert_enabled
   - Document: How to verify alert configuration

---

## Expected Outcomes

After fixes:
- ✅ All active coins have `alert_enabled=True` in database
- ✅ Backend logs show `ALERT_ALLOWED symbol=XXX alert_enabled=True source=db`
- ✅ UI matches database state (no discrepancies)
- ✅ BUY/SELL alerts are sent for enabled coins
- ✅ Startup logs show per-symbol configuration
- ✅ Blocking logs include source and suggested fix

---

## Verification Commands (AWS)

```bash
# 1. Check database state
docker exec -it <postgres_container> psql -U trader -d atp -c "SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled FROM watchlist_items WHERE is_deleted = false LIMIT 20;"

# 2. Check backend logs for startup config
docker logs <backend_container> | grep "STARTUP_ALERT_CONFIG"

# 3. Check backend logs for blocking messages
docker logs <backend_container> | grep "BLOQUEADO" | tail -20

# 4. Trigger test alert and verify
# (Use test endpoint or wait for real signal)
docker logs <backend_container> | grep "ALERT_ALLOWED" | tail -10

# 5. Verify API returns correct values
curl -X GET https://<api_url>/api/dashboard | jq '.[] | select(.symbol == "BTC_USDT") | {symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled}'
```

---

## Root Cause Summary (Plain English)

**The Problem:**
- Many database rows have `alert_enabled=False` because the default value is `False`
- When new rows are created or migrated, they default to `False` unless explicitly set to `True`
- The frontend UI shows alerts as enabled (YES), but the database has them as disabled (False)
- The backend signal monitor only processes coins with `alert_enabled=True`, so alerts are blocked

**The Fix:**
1. Run a migration to set `alert_enabled=True` for all active coins (one-time fix)
2. Add logging to show alert configuration on startup and when alerts are blocked
3. Ensure the database is the single source of truth (no caching, no defaults in API serialization)
4. Add validation to prevent this from happening again (constraints, startup checks)
