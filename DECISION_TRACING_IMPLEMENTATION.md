# Decision Tracing Implementation Summary

## Overview
This document summarizes the implementation of decision tracing for buy order attempts. The system now tracks why buy orders are SKIPPED or FAILED with structured reason codes, human-readable messages, and contextual data.

## Files Changed

### Backend

1. **`backend/app/utils/decision_reason.py`** (NEW)
   - Created DecisionReason helper module with:
     - `DecisionType` enum (SKIPPED/FAILED)
     - `ReasonCode` enum with canonical reason codes
     - `DecisionReason` dataclass
     - `make_skip()` and `make_fail()` helper functions
     - `classify_exchange_error()` function to map exchange errors to reason codes

2. **`backend/app/models/telegram_message.py`**
   - Added new fields:
     - `decision_type` (VARCHAR(20)) - "SKIPPED" or "FAILED"
     - `reason_code` (VARCHAR(100)) - Canonical reason code
     - `reason_message` (TEXT) - Human-readable reason
     - `context_json` (JSONB) - Contextual data (prices, balances, thresholds)
     - `exchange_error_snippet` (TEXT) - Raw exchange error for FAILED decisions
     - `correlation_id` (VARCHAR(100)) - Correlation ID for tracing

3. **`backend/migrations/add_decision_tracing_fields.sql`** (NEW)
   - Database migration to add new fields to `telegram_messages` table
   - Includes indexes for efficient queries
   - Backward compatible (allows NULL for existing rows)

4. **`backend/app/api/routes_monitoring.py`**
   - Updated `add_telegram_message()` to accept DecisionReason fields
   - Updated `/monitoring/telegram-messages` endpoint to return new fields
   - Updated in-memory fallback to include new fields

5. **`backend/app/services/signal_monitor.py`**
   - Updated `_emit_lifecycle_event()` to accept optional `decision_reason` parameter
   - Updated TRADE_BLOCKED and ORDER_FAILED event handlers to extract and store DecisionReason fields
   - Added DecisionReason recording for:
     - Trade disabled check (`TRADE_DISABLED`)
     - Invalid trade amount check (`INVALID_TRADE_AMOUNT`)
     - Insufficient balance check (`INSUFFICIENT_AVAILABLE_BALANCE`)
     - Max open orders check (`MAX_OPEN_TRADES_REACHED`)
     - Recent orders cooldown check (`RECENT_ORDERS_COOLDOWN`)
     - Guardrail blocked check (`GUARDRAIL_BLOCKED`)
     - Order placement failures (`EXCHANGE_REJECTED`, `INSUFFICIENT_FUNDS`, `AUTHENTICATION_ERROR`, etc.)

### Frontend

6. **`frontend/src/app/api.ts`**
   - Updated `TelegramMessage` interface to include new decision tracing fields

7. **`frontend/src/app/components/MonitoringPanel.tsx`**
   - Updated telegram message display to show:
     - Decision type badge (SKIPPED/FAILED) with color coding
     - Reason code (monospace font)
     - Reason message (prominent display)
     - Expandable "Details" dropdown showing:
       - Decision type
       - Reason code
       - Reason message
       - Exchange error snippet (for FAILED decisions)
       - Context JSON (pretty-printed)
       - Correlation ID

## Reason Codes Implemented

### Skip Reasons
- `TRADE_DISABLED` - Trade flag is NO/disabled
- `ALERT_DISABLED` - Alert is disabled
- `COOLDOWN_ACTIVE` - Cooldown period active
- `ALREADY_HAS_OPEN_ORDER` - Already has open order
- `MAX_OPEN_TRADES_REACHED` - Maximum open trades limit reached
- `PRICE_ABOVE_BUY_TARGET` - Price above buy target
- `PRICE_NOT_IN_RANGE` - Price not in buy range
- `RSI_NOT_LOW_ENOUGH` - RSI not low enough
- `STRATEGY_DISALLOWS_BUY` - Strategy disallows buy
- `INSUFFICIENT_AVAILABLE_BALANCE` - Insufficient balance for order
- `MIN_NOTIONAL_NOT_MET` - Order size below minimum notional
- `THROTTLED_DUPLICATE_ALERT` - Alert throttled as duplicate
- `DATA_MISSING` - Required data missing (price/indicators)
- `SAFETY_GUARD` - Safety guard triggered
- `NO_SIGNAL` - No buy signal detected
- `INVALID_TRADE_AMOUNT` - Invalid or missing trade amount
- `RECENT_ORDERS_COOLDOWN` - Recent orders cooldown active
- `GUARDRAIL_BLOCKED` - Trading guardrail blocked order

### Fail Reasons
- `EXCHANGE_REJECTED` - Exchange rejected the order
- `INSUFFICIENT_FUNDS` - Insufficient funds (includes margin)
- `SIGNATURE_ERROR` - Signature error
- `RATE_LIMIT` - Rate limit exceeded
- `TIMEOUT` - Request timeout
- `AUTHENTICATION_ERROR` - Authentication failed (401, 40101, 40103)
- `MIN_NOTIONAL_NOT_MET` - Order below minimum notional
- `EXCHANGE_ERROR_UNKNOWN` - Unknown exchange error

## Implementation Status

### ✅ Completed

1. DecisionReason model/helper created
2. TelegramMessage model updated with new fields
3. Database migration created
4. `_emit_lifecycle_event` updated to accept DecisionReason
5. Critical guard clauses updated to record SKIP reasons:
   - Trade disabled check
   - Invalid trade amount check
   - Insufficient balance check
   - Max open orders check (final verification)
   - Recent orders cooldown check (final verification)
   - Guardrail blocked check
6. Order creation failure handling updated to record FAIL reasons
7. API endpoint updated to return new fields
8. Frontend interface updated
9. Monitor UI updated to display decision fields

### 🔄 Additional Work Recommended

1. **Alert Blocking Path** (lines ~1846-1857 in signal_monitor.py)
   - Update alert blocking section to include DecisionReason when alerts are throttled
   - This would require updating `should_emit_signal()` or the alert blocking logic

2. **More Guard Clauses**
   - Update remaining guard clauses in the main monitoring loop (around lines 2697-2783)
   - These prevent `_create_buy_order()` from being called, so they should record SKIP reasons at that level

3. **Logging Enhancement**
   - Add correlation_id to all decision logs
   - Ensure correlation_id is generated early in the decision flow and passed through

4. **Telegram Notifications**
   - For FAILED decisions, ensure Telegram failure notification includes reason_code and reason_message
   - Currently implemented for order failures but could be enhanced

## Testing

To verify the implementation:

1. **Run database migration:**
   ```bash
   psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql
   ```

2. **Test scenarios:**
   - Disable trade flag → Should see SKIPPED with TRADE_DISABLED
   - Remove trade_amount_usd → Should see SKIPPED with INVALID_TRADE_AMOUNT
   - Insufficient balance → Should see SKIPPED with INSUFFICIENT_AVAILABLE_BALANCE
   - Max open orders → Should see SKIPPED with MAX_OPEN_TRADES_REACHED
   - Recent orders cooldown → Should see SKIPPED with RECENT_ORDERS_COOLDOWN
   - Force buy with invalid params → Should see FAILED with appropriate reason code

3. **Verify Monitor UI:**
   - Check that blocked messages show decision type, reason code, and reason message
   - Verify expandable details show context JSON and exchange error (for FAILED)
   - Ensure correlation_id is visible in details

## Notes

- All changes are backward compatible
- Existing rows will have NULL for new fields until populated
- DecisionReason is optional in `_emit_lifecycle_event()` for backward compatibility
- Correlation IDs are generated using UUID v4

