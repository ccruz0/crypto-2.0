# Investigation: Decision Tracing Missing for Some Alerts

## Problem

Alerts are being sent successfully (e.g., TRX_USDT at 03:41:19), but:
- ❌ No order is created
- ❌ No decision tracing is recorded (decision_type, reason_code are NULL)

## Database Evidence

```sql
SELECT id, symbol, blocked, decision_type, reason_code, timestamp 
FROM telegram_messages 
WHERE id IN (140705, 140704);

 id   |  symbol  | blocked | decision_type | reason_code |           timestamp           
------+----------+---------+---------------+-------------+-------------------------------
140704| TRX_USDT | f       |               |             | 2026-01-09 03:41:19.251544+00
140705| TRX_USDT | f       |               |             | 2026-01-09 03:41:19.330082+00
```

## Root Cause Analysis

### Expected Behavior

When `blocked_by_limits=True`:
1. Guard clause checks (MAX_OPEN_ORDERS or RECENT_ORDERS_COOLDOWN) should emit decision tracing
2. `should_create_order=False` is set
3. Code skips `if should_create_order:` block
4. Decision tracing should already be in database from guard clause

### Actual Behavior

Decision tracing is NOT being emitted. Possible reasons:

1. **Guard clauses emit decision tracing, but `_emit_lifecycle_event` fails silently**
   - Check if there are exceptions in `_emit_lifecycle_event`
   - Check if `add_telegram_message` is failing

2. **Alert is sent BEFORE guard clause checks**
   - Alert sending happens in lines 765-965 (before order creation logic)
   - Guard clause checks happen in lines 2803-2925
   - If alert is sent but then guard clauses don't run, no decision tracing

3. **Guard clause conditions are not met, but order is still blocked**
   - `blocked_by_limits` might be set to True without entering guard clauses
   - Need to check if there's a code path where `blocked_by_limits=True` without guard clause execution

## Code Flow Analysis

### Alert Sending (Lines 765-965)
- Happens BEFORE order creation logic
- If alert is sent successfully, `buy_alert_sent_successfully=True`

### Order Creation Logic (Lines 2793-3621)
1. **Guard Clause Checks (Lines 2803-2925)**
   - MAX_OPEN_ORDERS check → emits decision tracing
   - RECENT_ORDERS_COOLDOWN check → emits decision tracing
   - Sets `blocked_by_limits=True` if blocked

2. **should_create_order Logic (Lines 2931-2947)**
   - If `blocked_by_limits=True` → `should_create_order=False`
   - Otherwise → `should_create_order=True`

3. **Order Creation Block (Lines 2971-3621)**
   - `if should_create_order:` → enters block, creates order
   - **NO ELSE CLAUSE** → if `should_create_order=False`, code continues to SELL handling

## Fix Applied

Added else clause to `if should_create_order:` block (line 3621) to log when order is blocked.

However, this doesn't fix the root cause - decision tracing should already be emitted in guard clauses.

## Next Steps

1. **Check logs for exceptions in `_emit_lifecycle_event`**
   - Look for "Failed to emit lifecycle event" warnings
   - Check if `add_telegram_message` is throwing exceptions

2. **Verify guard clauses are actually executing**
   - Check logs for "[DECISION]" entries
   - Verify guard clause conditions are being met

3. **Check if there's a code path where order is blocked without guard clause execution**
   - Look for other places where `should_create_order=False` is set
   - Check if there are early returns before guard clauses

4. **Test with DEBUG_TRADING=1**
   - Enable detailed logging
   - Trigger another alert
   - Check logs for decision tracing emission

## Status

- ✅ Added else clause for logging
- ⚠️ Root cause still needs investigation
- 🔍 Need to check logs for exceptions or missing guard clause execution

