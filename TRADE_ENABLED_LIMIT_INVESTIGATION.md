# Trade Enabled Limit Investigation Report

## Summary
Investigation into the reported issue where enabling a 17th coin with `trade_enabled=True` causes one coin to be automatically disabled, maintaining a limit of 16 coins.

## Findings

### 1. Confirmed Behavior
- **Current State**: 16 coins have `trade_enabled=True` (confirmed via API)
- **Test Result**: When LINK_USDT was enabled as the 17th coin:
  - LINK_USDT was immediately disabled (`trade_enabled: false`)
  - Count remained at 17, but LINK_USDT is not in the enabled list
  - ALGO_USDT appeared in the enabled list instead
  - This confirms the user's observation

### 2. Code Analysis
- **No explicit limit found**: Searched entire codebase for:
  - Hardcoded limit of 16
  - MAX_TRADE_ENABLED constants
  - Count checks that disable coins
  - Database constraints or triggers
- **Logging in place**: Added logging code in `routes_dashboard.py` that should detect automatic disabling:
  - `[TRADE_ENABLED_COUNT_MISMATCH]` warnings
  - `[TRADE_ENABLED_COUNT_VERIFIED]` confirmations

### 3. Architecture Notes
- System uses two tables:
  - `watchlist_items`: Legacy table
  - `watchlist_master`: Source of truth (newer)
- Updates can happen via:
  - `PUT /dashboard/{item_id}` - Updates watchlist_items, then syncs to watchlist_master
  - `PUT /dashboard/symbol/{symbol}` - Updates watchlist_master directly
- Both endpoints have count verification logging

## Next Steps

### 1. Check AWS Backend Logs
The logging code should have captured the automatic disabling. Check logs for:

```bash
# Option 1: Via Docker
ssh ubuntu@175.41.189.249
docker compose --profile aws logs backend-aws | grep -E "TRADE_ENABLED_COUNT|COUNT_MISMATCH|LINK_USDT" | tail -50

# Option 2: Direct log file
ssh ubuntu@175.41.189.249
tail -500 ~/automated-trading-platform/backend/backend.log | grep -E "TRADE_ENABLED_COUNT|COUNT_MISMATCH|LINK_USDT" | tail -50
```

Look for:
- `[TRADE_ENABLED_COUNT_MISMATCH]` - Indicates automatic disabling detected
- `[TRADE_ENABLED_ENABLE]` - When LINK_USDT was enabled
- `[TRADE_ENABLED_DISABLE]` - When LINK_USDT or another coin was disabled
- Any PUT requests that modified trade_enabled after the initial enable

### 2. Check Database Triggers
If no code is found, check for database-level triggers:

```sql
-- PostgreSQL: Check for triggers on watchlist_items
SELECT trigger_name, event_manipulation, event_object_table, action_statement
FROM information_schema.triggers
WHERE event_object_table IN ('watchlist_items', 'watchlist_master');

-- Check for constraints
SELECT constraint_name, constraint_type, table_name
FROM information_schema.table_constraints
WHERE table_name IN ('watchlist_items', 'watchlist_master')
AND constraint_type != 'UNIQUE';
```

### 3. Check for Background Tasks
Look for any scheduled tasks or background workers that might be modifying trade_enabled:

```bash
# Check for cron jobs or scheduled tasks
ssh ubuntu@175.41.189.249
crontab -l
ps aux | grep -i "python.*trade\|python.*watchlist\|python.*signal"
```

### 4. Monitor Real-Time
Enable another coin and immediately check logs:

1. Enable a coin with `trade_enabled=False` (e.g., SUI_USDT)
2. Immediately check backend logs:
   ```bash
   tail -f ~/automated-trading-platform/backend/backend.log | grep -E "TRADE_ENABLED|COUNT"
   ```
3. Check if any other coin gets disabled
4. Note the exact timestamp and sequence of events

## Possible Causes

1. **Database Trigger**: A PostgreSQL trigger that enforces a limit
2. **Background Task**: A scheduled job that periodically checks and enforces limits
3. **Race Condition**: Multiple concurrent requests causing unexpected behavior
4. **Frontend Logic**: Frontend code that automatically disables coins (unlikely, but possible)
5. **Signal Monitor Service**: The `SignalMonitorService` might have logic that modifies trade_enabled

## Files to Review

- `backend/app/api/routes_dashboard.py` - Main update endpoints (lines 1287-1319, 1876-1908)
- `backend/app/models/watchlist.py` - Database models
- `backend/app/services/signal_monitor.py` - Signal monitoring service
- Database migration files in `backend/scripts/`

## Test Performed

**Date**: 2025-12-27
**Action**: Enabled LINK_USDT (17th coin)
**Result**: 
- LINK_USDT was enabled then immediately disabled
- Count shows 17, but LINK_USDT not in list
- ALGO_USDT in enabled list (was not in original 16)

## Recommendations

1. **Immediate**: Check AWS backend logs for `[TRADE_ENABLED_COUNT_MISMATCH]` warnings
2. **Short-term**: 
   - Run `backend/scripts/add_trade_enabled_audit_logging.py` to check for database triggers
   - Add more detailed logging around the commit point to catch any code that modifies trade_enabled
   - Monitor logs in real-time when enabling a 17th coin
3. **Long-term**: If a limit is intentional, make it explicit and configurable rather than hidden

## Scripts Created

- `backend/scripts/add_trade_enabled_audit_logging.py` - Checks for database triggers and current state

