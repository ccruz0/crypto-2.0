# BTC BUY INDEX Spam Fix

## Problem Summary

The `BuyIndexMonitorService` was sending BTC BUY INDEX alerts every 2 minutes, even after recent fixes. The root cause was:

1. **Missing Database Table**: The `signal_throttle_states` table did not exist in the database, preventing throttling state from being persisted.

2. **Column Size Issue**: The `side` column in `signal_throttle_states` was defined as `VARCHAR(4)`, but `BuyIndexMonitorService` was trying to insert "INDEX" (5 characters), causing `StringDataRightTruncation` errors.

## Root Cause Analysis

### Investigation Steps

1. **Container Inventory**: Confirmed only one `backend-aws` container is running (no duplicate services).

2. **Process Check**: No zombie Python processes outside Docker running index monitors.

3. **Systemd/Cron Check**: No systemd services or cron jobs running separate index monitors.

4. **Log Analysis**: Found that `BuyIndexMonitorService` in `backend-aws` was:
   - Sending alerts every 2 minutes
   - Logging: `"Failed to load throttle state for BTC_USD buy index: (psycopg2.errors.UndefinedTable) relation \"signal_throttle_states\" does not exist"`
   - Always returning `"No previous same-side signal recorded"` because the table didn't exist

## Solution

### 1. Created Missing Table

Executed SQL to create the `signal_throttle_states` table:

```python
from app.models.signal_throttle import SignalThrottleState
Base.metadata.create_all(bind=engine, tables=[SignalThrottleState.__table__])
```

### 2. Fixed Column Size

- **Model Update**: Changed `side` column from `String(4)` to `String(10)` in `backend/app/models/signal_throttle.py`
- **Database Migration**: Executed `ALTER TABLE signal_throttle_states ALTER COLUMN side TYPE VARCHAR(10)`

### 3. Verification

After the fixes:
- The table now exists and throttle state can be persisted
- The `side` column accepts "INDEX" (5 characters)
- `BuyIndexMonitorService` should now respect the throttle rules:
  - 10 minutes minimum interval OR
  - 1% price change minimum

## Files Changed

1. `backend/app/models/signal_throttle.py`: Updated `side` column size from `String(4)` to `String(10)`
2. Database: Created `signal_throttle_states` table and altered `side` column

## Commands Executed

```bash
# Create the table
docker compose exec backend-aws python3 -c "
from app.database import engine, Base
from app.models.signal_throttle import SignalThrottleState
Base.metadata.create_all(bind=engine, tables=[SignalThrottleState.__table__])
"

# Fix column size
docker compose exec backend-aws python3 -c "
from sqlalchemy import text
from app.database import engine
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE signal_throttle_states ALTER COLUMN side TYPE VARCHAR(10)'))
    conn.commit()
"
```

## Expected Behavior After Fix

- BTC BUY INDEX alerts should only be sent when:
  - At least 10 minutes have passed since the last alert, OR
  - Price has changed by at least 1% since the last alert
- The throttle state is now persisted in the database, so the service remembers previous alerts across restarts
- No more "Failed to persist buy index throttle state" errors

## Notes

- The `BuyIndexMonitorService` is still using hardcoded `BTC_USD` instead of resolving from the Watchlist. This is a separate issue that should be addressed in a future update to align with the Watchlist symbol resolution (preferring `BTC_USDT`).
- The local in-memory throttle guard in `BuyIndexMonitorService` provides a fallback, but the database-backed throttle is now the primary mechanism.


