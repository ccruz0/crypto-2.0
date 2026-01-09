# Troubleshooting: No Blocked Messages in Monitor

## Problem
You're receiving alerts in Telegram, but the Monitor UI shows "0" blocked/throttled messages.

## Root Causes

### 1. Database Migration Not Run (Most Likely)
The new decision tracing columns don't exist in the database yet, so:
- Messages can't be saved with decision tracing fields
- The API might be failing silently when trying to save
- Even if messages are saved, they won't have the new fields

**Solution:** Run the database migration first.

### 2. Alerts Sent But Not Marked as Blocked
When alerts are sent successfully to Telegram, they're recorded with `blocked=False`. The Monitor UI only shows messages where `blocked=True`. 

If a buy order is skipped or failed AFTER the alert is sent, we need to ensure `_emit_lifecycle_event` is called with `TRADE_BLOCKED` or `ORDER_FAILED` to create a `blocked=True` entry.

## Diagnostic Steps

### Step 1: Check Migration Status

Run the diagnostic script:

```bash
# On AWS server
cd ~/automated-trading-platform
python3 backend/scripts/check_decision_tracing.py

# Or via Docker
docker compose --profile aws exec backend-aws python3 backend/scripts/check_decision_tracing.py
```

This will tell you:
- ✅ If migration has been run (columns exist)
- 📊 Recent blocked messages and their decision tracing fields
- 📊 Recent sent messages
- 📊 Overall statistics

### Step 2: Run Migration (If Needed)

If the diagnostic shows missing columns, run the migration:

```bash
# Option 1: Direct PostgreSQL
psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql

# Option 2: Via Docker Compose
docker compose --profile aws exec -T db psql -U trader -d atp < backend/migrations/add_decision_tracing_fields.sql

# Option 3: Copy file first, then run
docker compose --profile aws cp backend/migrations/add_decision_tracing_fields.sql db:/tmp/
docker compose --profile aws exec -T db psql -U trader -d atp -f /tmp/add_decision_tracing_fields.sql
```

### Step 3: Verify Migration

After running the migration, verify it worked:

```sql
SELECT 
    column_name, 
    data_type, 
    is_nullable
FROM information_schema.columns 
WHERE table_name = 'telegram_messages' 
AND column_name IN ('decision_type', 'reason_code', 'reason_message', 'context_json', 'exchange_error_snippet', 'correlation_id')
ORDER BY column_name;
```

Expected: 6 rows (one for each new column)

### Step 4: Check Backend Logs

Look for decision tracing logs:

```bash
# On AWS server
docker compose --profile aws logs backend-aws | grep -i "DECISION\|TRADE_BLOCKED\|ORDER_FAILED" | tail -50

# Or check specific symbol
docker compose --profile aws logs backend-aws | grep -i "BTC_USD.*DECISION" | tail -20
```

You should see logs like:
```
[DECISION] symbol=BTC_USD decision=SKIPPED reason=TRADE_DISABLED context={...}
```

### Step 5: Test with a Known Block Scenario

To verify the system is working, temporarily disable trading for a symbol:

1. Go to Dashboard → Watchlist
2. Find a symbol that's currently active
3. Set `trade_enabled = False` for that symbol
4. Wait for the next alert to be generated
5. Check Monitor → Telegram (Mensajes Bloqueados)

You should see:
- A blocked message with `decision_type=SKIPPED`
- `reason_code=TRADE_DISABLED`
- `reason_message` explaining why
- Context JSON with `trade_enabled: false`

## Expected Behavior After Fix

Once the migration is run and the system is working correctly:

1. **When an alert is sent to Telegram:**
   - Alert appears in Telegram ✅
   - Alert is recorded in database with `blocked=False` (normal)

2. **When buy order is skipped (e.g., trade_enabled=False):**
   - Alert still sent to Telegram ✅
   - A SEPARATE entry is created with `blocked=True`
   - This entry has `decision_type=SKIPPED`, `reason_code`, `reason_message`
   - This entry appears in Monitor → Telegram (Mensajes Bloqueados)

3. **When buy order fails (e.g., exchange error):**
   - Alert sent to Telegram ✅
   - A SEPARATE entry is created with `blocked=True`
   - This entry has `decision_type=FAILED`, `reason_code`, `reason_message`, `exchange_error_snippet`
   - This entry appears in Monitor → Telegram (Mensajes Bloqueados)
   - A Telegram failure notification is also sent

## Quick Fix Checklist

- [ ] Run diagnostic script: `python3 backend/scripts/check_decision_tracing.py`
- [ ] If migration not run: Execute `add_decision_tracing_fields.sql`
- [ ] Verify migration: Check columns exist in database
- [ ] Restart backend: `docker compose --profile aws restart backend-aws`
- [ ] Check logs: Look for `[DECISION]` entries
- [ ] Test: Disable trading for a symbol, wait for alert, check Monitor
- [ ] Verify: Blocked message appears with decision_type, reason_code, reason_message

## Still Not Working?

If messages still don't appear after running the migration:

1. **Check if `_emit_lifecycle_event` is being called:**
   ```bash
   docker compose --profile aws logs backend-aws | grep "_emit_lifecycle_event\|TRADE_BLOCKED" | tail -50
   ```

2. **Check database directly:**
   ```sql
   SELECT id, symbol, blocked, decision_type, reason_code, reason_message, timestamp 
   FROM telegram_messages 
   WHERE timestamp >= NOW() - INTERVAL '1 day'
   ORDER BY timestamp DESC 
   LIMIT 20;
   ```

3. **Check API endpoint:**
   ```bash
   curl http://your-aws-host:8000/api/monitoring/telegram-messages | jq '.messages[0]'
   ```

4. **Check for errors in backend logs:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -i "error\|exception\|failed" | tail -50
   ```

## Common Issues

### Issue: Migration fails with "column already exists"
**Solution:** The migration is idempotent - it checks if columns exist before adding them. This is normal if you run it multiple times.

### Issue: Messages saved but decision_type is NULL
**Solution:** This means `_emit_lifecycle_event` is being called but without a `decision_reason` parameter. Check that all skip/fail paths are creating `DecisionReason` objects and passing them to `_emit_lifecycle_event`.

### Issue: Messages appear in database but not in Monitor UI
**Solution:** 
- Check browser console for errors
- Verify API returns messages: `curl http://your-host/api/monitoring/telegram-messages`
- Clear browser cache
- Check if frontend is filtering messages incorrectly

