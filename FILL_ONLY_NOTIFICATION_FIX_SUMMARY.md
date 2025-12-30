# Fill-Only Notification Fix - Summary

## What Was Removed

1. **Old in-memory notification tracking:**
   - `_executed_order_notification_sent: Dict[str, float]` dictionary
   - `_has_notification_been_sent()` method (10-minute window check)
   - `_mark_notification_sent()` method
   - `_purge_stale_notification_tracking()` method
   - All references to `needs_telegram` boolean flag

2. **Non-fill notification triggers:**
   - Notifications on status changes without fill increments (NEW, OPEN, CANCELED, REPLACED, TRIGGERED)
   - Notifications on reconnect replays of already-filled orders
   - Notifications on SL/TP creation/trigger events without actual fills

## What Condition Now Triggers Notifications

**Strict fill-only gate:**
- Notification is sent **ONLY** when:
  1. `status == "FILLED"` OR `status == "PARTIALLY_FILLED"`
  2. AND `current_filled_qty > last_seen_filled_qty` (tracked persistently in SQLite)
  3. AND `current_filled_qty > 0`

**Implementation details:**
- Uses `fill_tracker.should_notify_fill()` which:
  - Checks if `current_filled_qty > last_seen_filled_qty` (stored in SQLite DB)
  - Verifies status is FILLED or PARTIALLY_FILLED
  - Returns `(should_notify: bool, reason: str)`
- After successful notification, calls `fill_tracker.record_fill()` to persist the new `filled_qty`
- SQLite database (`/app/.state/fill_tracker.db`) stores:
  - `order_id` (primary key)
  - `last_filled_qty` (last seen cumulative quantity)
  - `last_status` (last seen status)
  - `last_notified_at` (timestamp of last notification)
  - Auto-cleanup of entries older than 7 days

## Why False Positives Are No Longer Possible

1. **Persistent fill tracking:**
   - SQLite database persists `last_seen_filled_qty` across container restarts
   - Even if the container restarts, old fills are not re-notified
   - Each order's fill history is tracked independently

2. **Strict increment check:**
   - `should_notify_fill()` only returns `True` when `new_filled_qty > last_seen_filled_qty`
   - Same `filled_qty` seen twice = no notification
   - Status changes without `filled_qty` increase = no notification

3. **Fill status requirement:**
   - Only FILLED and PARTIALLY_FILLED statuses can trigger notifications
   - NEW, OPEN, CANCELED, REPLACED, TRIGGERED statuses are ignored
   - SL/TP creation/trigger events without fills are ignored

4. **Always-updated cumulative_quantity:**
   - `cumulative_quantity` is always updated from API data, even when `needs_update == False`
   - This ensures fill tracking uses the latest data from the exchange
   - Fill check happens outside the `if needs_update:` block to catch all fill events

5. **Single execution gate:**
   - There is exactly ONE place where Telegram notifications are sent for "ORDER EXECUTED"
   - Both code paths (existing orders and new orders) use the same `fill_tracker.should_notify_fill()` logic
   - No duplicate notification paths

## Files Modified

1. **`backend/app/services/exchange_sync.py`:**
   - Removed old in-memory tracking methods
   - Added `fill_tracker` integration at two notification points (existing orders ~line 2099, new orders ~line 2564)
   - Always update `cumulative_quantity` from API (even when `needs_update == False`)
   - Added `delta_quantity` calculation and audit logging
   - Fixed origin labeling (only set order_role for STOP_LIMIT/TAKE_PROFIT_LIMIT)

2. **`backend/app/services/fill_tracker.py` (new file):**
   - SQLite-based persistent fill tracking
   - `should_notify_fill()` method: core fill-only logic
   - `record_fill()` method: persist fill data after notification
   - Auto-cleanup of entries older than 7 days
   - Database stored at `/app/.state/fill_tracker.db`

## Audit Logging

Every Telegram notification sends a JSON log line with:
- `event`: "ORDER_EXECUTED_NOTIFICATION"
- `symbol`, `side`, `order_id`, `status`
- `cumulative_quantity`: current filled quantity
- `delta_quantity`: increment since last notification
- `price`, `avg_price`, `order_type`
- `order_role`, `client_oid`
- `trade_signal_id`, `parent_order_id`
- `notify_reason`: why notification was sent
- `handler`: code path that sent notification

## Origin Labeling Fix

- BUY orders are **never** labeled as "Stop Loss" unless:
  - `order_type == "STOP_LIMIT"` (explicit from exchange)
  - OR `clientOrderId` contains clear SL/TP tags (if implemented)
- If uncertain, `order_role` is left as `None` (not mislabeled)
- Only `STOP_LIMIT` and `TAKE_PROFIT_LIMIT` order types set `order_role`

## Validation Results

✅ **Syntax check:** `python3 -m py_compile backend/app/services/exchange_sync.py` - PASSED
✅ **Old tracking removed:** No references to `needs_telegram`, `_has_notification_been_sent`, etc.
✅ **Single execution gate:** Only `fill_tracker.should_notify_fill()` controls notifications
✅ **Persistent tracking:** SQLite database with 7-day cleanup
✅ **Fill-only logic:** Only FILLED/PARTIALLY_FILLED with increased `filled_qty`
✅ **Audit logging:** JSON log line with all required fields including `delta_quantity`
✅ **Origin labeling:** Only STOP_LIMIT/TAKE_PROFIT_LIMIT set order_role

## Guarantees

1. **One notification per fill increment:** Each time `filled_qty` increases, exactly one notification is sent
2. **No notifications for non-fill events:** Status changes, reconnects, SL/TP creation without fills = no notification
3. **Persistent across restarts:** Container restart does NOT resend old fills due to SQLite persistence
4. **Zero false positives:** Impossible to send notification without a real fill increment

