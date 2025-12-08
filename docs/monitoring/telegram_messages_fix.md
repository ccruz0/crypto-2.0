# Telegram Messages Panel Fix

## Problem Summary

The Monitoring → Telegram Messages panel was showing empty even though messages had been sent earlier.

## Root Cause

The `telegram_messages` table did not exist in the database. The backend code was:
1. Calling `add_telegram_message()` which tried to save messages to the database
2. The `/monitoring/telegram-messages` endpoint was querying the database
3. But the table didn't exist, so:
   - Insertions were failing silently (caught by exception handlers)
   - Queries returned empty results
   - The frontend showed an empty panel

## Solution

### 1. Created Missing Table

Created the `telegram_messages` table with the following schema:

```sql
CREATE TABLE telegram_messages (
    id SERIAL PRIMARY KEY,
    message TEXT NOT NULL,
    symbol VARCHAR(50),
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    throttle_status VARCHAR(20),
    throttle_reason TEXT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
)
```

### 2. Created Indexes

Created indexes for efficient queries:
- `ix_telegram_messages_timestamp` - for time-based filtering
- `ix_telegram_messages_symbol` - for symbol lookups
- `ix_telegram_messages_blocked` - for filtering blocked messages
- `ix_telegram_messages_symbol_blocked` - composite index for common queries

### 3. Cleaned Up Duplicate Code

Removed duplicate `get_signal_throttle` function definitions in `routes_monitoring.py` (there were 8 duplicates).

## Files Changed

1. **Database**: Created `telegram_messages` table
2. **backend/scripts/create_telegram_messages_table.py**: Migration script for reference
3. **backend/app/api/routes_monitoring.py**: Removed duplicate code

## Verification

After the fix:
- The table exists and is ready to receive messages
- The `add_telegram_message()` function will now successfully persist messages
- The `/monitoring/telegram-messages` endpoint will return messages from the database
- New Telegram messages (BUY/SELL alerts, BTC index updates, etc.) will appear in the Monitoring panel

## Expected Behavior

- All Telegram messages sent by the system (via `telegram_notifier.py`) are now persisted to the database
- Messages are kept for 30 days (as configured in the endpoint)
- The Monitoring panel will show:
  - Sent messages (`blocked=False`)
  - Blocked messages (`blocked=True`) with throttle reasons
  - Messages sorted by timestamp (newest first)
  - Up to 500 most recent messages

## Notes

- Historical messages sent before the table was created are not available (the table was empty when created)
- Future messages will be properly persisted and visible in the UI
- The system has duplicate detection (5-second window) to prevent duplicate entries from multiple workers











