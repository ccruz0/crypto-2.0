# Trade Enabled 16-Coin Limit Investigation

## Problem
When enabling more than 16 coins with `trade_enabled=True`, one of them automatically turns off.

## Investigation Summary

### ✅ What We've Checked

1. **Frontend Code** (`frontend/src/app/page.tsx`)
   - No explicit limit of 16 found
   - Fast/slow queue logic doesn't limit count
   - No validation preventing more than 16 coins

2. **Backend API Routes** (`backend/app/api/routes_dashboard.py`)
   - No explicit limit of 16 found
   - Added comprehensive logging to track:
     - When `trade_enabled` is enabled/disabled
     - Count of coins with `trade_enabled=True` before/after changes
     - Detection of unexpected count changes

3. **Database Schema**
   - No triggers found that enforce a limit
   - No constraints found that limit `trade_enabled` count
   - Checked migration files: no limits defined

4. **Signal Monitor Service** (`backend/app/services/signal_monitor.py`)
   - No logic that disables `trade_enabled` based on count
   - Only checks `trade_enabled` status, doesn't modify it

### 🔍 Logging Added

The following log messages will help identify the issue:

- `[TRADE_ENABLED_ENABLE]` - When enabling trade_enabled
- `[TRADE_ENABLED_DISABLE]` - When disabling trade_enabled  
- `[TRADE_ENABLED_COUNT_MISMATCH]` - **KEY INDICATOR** - Detects when count changes unexpectedly
- `[TRADE_ENABLED_COUNT_VERIFIED]` - Confirms count matches expected value

## Monitoring Tools

### 1. Real-time Log Monitoring

Use the monitoring script to watch backend logs in real-time:

```bash
# Monitor backend logs (adjust path to your log file)
tail -f /path/to/backend.log | python backend/scripts/monitor_trade_enabled_limit.py

# Or if logs are in Docker:
docker compose logs -f backend | python backend/scripts/monitor_trade_enabled_limit.py
```

The script will:
- Show all trade_enabled enable/disable events
- Alert when count mismatches are detected
- Display recent event history when issues occur

### 2. Manual Log Search

Search for count mismatches in logs:

```bash
# Search for count mismatches (indicates automatic disabling)
grep "TRADE_ENABLED_COUNT_MISMATCH" /path/to/backend.log

# Search for all trade_enabled changes
grep "TRADE_ENABLED" /path/to/backend.log | tail -50

# Search for watchlist updates
grep "WATCHLIST_UPDATE.*trade_enabled" /path/to/backend.log | tail -50
```

### 3. Database Query

Check current count directly:

```sql
-- Count coins with trade_enabled=True
SELECT COUNT(*) 
FROM watchlist_items 
WHERE trade_enabled = TRUE 
  AND is_deleted = FALSE;

-- List all coins with trade_enabled=True
SELECT symbol, exchange, trade_enabled, updated_at
FROM watchlist_items 
WHERE trade_enabled = TRUE 
  AND is_deleted = FALSE
ORDER BY updated_at DESC;
```

## Reproducing the Issue

1. **Enable monitoring:**
   ```bash
   tail -f /path/to/backend.log | python backend/scripts/monitor_trade_enabled_limit.py
   ```

2. **In the dashboard, enable Trade YES for coins until you have 16**

3. **Try to enable the 17th coin**

4. **Watch the monitoring output for:**
   - `[TRADE_ENABLED_ENABLE]` for the 17th coin
   - `[TRADE_ENABLED_COUNT_MISMATCH]` - This will show if one was automatically disabled
   - `[TRADE_ENABLED_DISABLE]` - This will show which coin was disabled

## Possible Causes (To Investigate)

Since no explicit limit was found in the code, possible causes:

1. **Database Trigger** (not found in migrations, but could exist)
   - Check: `SELECT * FROM pg_trigger WHERE tgname LIKE '%trade%';`

2. **Background Service/Worker**
   - Check for any cron jobs or scheduled tasks
   - Check for any services that modify watchlist_items

3. **Race Condition**
   - Multiple concurrent updates might cause issues
   - Check for transaction conflicts

4. **Frontend State Management**
   - Frontend might be preventing saves after 16
   - Check browser console for errors

5. **API Rate Limiting**
   - Some API might be rate-limited to 16 concurrent trades
   - Check for rate limit errors in logs

## Next Steps

1. **Run the monitoring script** while reproducing the issue
2. **Check backend logs** for `[TRADE_ENABLED_COUNT_MISMATCH]` messages
3. **Check database triggers** directly:
   ```sql
   SELECT * FROM information_schema.triggers 
   WHERE trigger_name LIKE '%trade%' OR event_object_table = 'watchlist_items';
   ```
4. **Check for background services** that modify watchlist_items
5. **Monitor network requests** in browser DevTools when enabling the 17th coin

## Files Modified

- `backend/app/api/routes_dashboard.py` - Added logging for trade_enabled changes
- `backend/scripts/monitor_trade_enabled_limit.py` - Created monitoring script

