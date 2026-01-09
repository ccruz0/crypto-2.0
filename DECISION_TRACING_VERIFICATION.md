# Decision Tracing Verification Plan

## Implementation Summary

The decision tracing system has been successfully implemented. Every alert that ends up in the blocked/throttled bucket now shows the exact reason why a BUY was not executed.

## Files Modified

### Backend
1. `backend/app/utils/decision_reason.py` (NEW) - DecisionReason helper module
2. `backend/app/models/telegram_message.py` - Added decision tracing fields
3. `backend/migrations/add_decision_tracing_fields.sql` (NEW) - Database migration
4. `backend/app/api/routes_monitoring.py` - Updated to accept and return DecisionReason fields
5. `backend/app/services/signal_monitor.py` - Updated to record DecisionReason in all guard clauses and failures

### Frontend
6. `frontend/src/app/api.ts` - Updated TelegramMessage interface
7. `frontend/src/app/components/MonitoringPanel.tsx` - Updated to display decision fields

## Reason Codes Implemented

### Skip Reasons (BUY was not attempted)
- `TRADE_DISABLED` - Trade flag is NO
- `INVALID_TRADE_AMOUNT` - Trade amount not configured or invalid
- `INSUFFICIENT_AVAILABLE_BALANCE` - Insufficient balance for SPOT order
- `MAX_OPEN_TRADES_REACHED` - Maximum open orders limit reached
- `RECENT_ORDERS_COOLDOWN` - Recent orders cooldown active
- `GUARDRAIL_BLOCKED` - Trading guardrail blocked order
- `COOLDOWN_ACTIVE` - Alert cooldown/throttle active
- `THROTTLED_DUPLICATE_ALERT` - Alert throttled as duplicate

### Fail Reasons (BUY was attempted but failed)
- `EXCHANGE_REJECTED` - Exchange rejected the order
- `INSUFFICIENT_FUNDS` - Insufficient funds (includes margin errors 306, 609)
- `AUTHENTICATION_ERROR` - Authentication failed (401, 40101, 40103)
- `RATE_LIMIT` - Rate limit exceeded
- `TIMEOUT` - Request timeout
- `MIN_NOTIONAL_NOT_MET` - Order below minimum notional
- `SIGNATURE_ERROR` - Signature error
- `EXCHANGE_ERROR_UNKNOWN` - Unknown exchange error

## Verification Scenarios

### Scenario 1: Trade Flag NO → SKIP with TRADE_DISABLED
**Steps:**
1. Set trade_enabled=False for a symbol in watchlist
2. Trigger a BUY alert
3. Check Monitor tab → Blocked messages

**Expected:**
- Alert appears in blocked/throttled list
- Decision: SKIPPED
- Reason Code: TRADE_DISABLED
- Reason Message: "Trade is disabled for {symbol}. trade_enabled=False."
- Context JSON includes: symbol, trade_enabled, trade_amount_usd, price
- Telegram alert is sent (alert was sent, order was skipped)

### Scenario 2: Cooldown Active → SKIP with COOLDOWN_ACTIVE
**Steps:**
1. Send a BUY alert for a symbol
2. Within 60 seconds, trigger another BUY alert for same symbol
3. Check Monitor tab → Blocked messages

**Expected:**
- Alert appears in blocked/throttled list
- Decision: SKIPPED
- Reason Code: COOLDOWN_ACTIVE or THROTTLED_DUPLICATE_ALERT
- Reason Message includes cooldown information
- Context JSON includes: symbol, price, reference_price, reference_timestamp, throttle_reason
- Telegram alert is sent (alert was sent, but throttled/blocked)

### Scenario 3: Open Order Exists → SKIP with ALREADY_HAS_OPEN_ORDER
**Note:** This scenario may not apply if max open orders is checked first. The actual reason would be MAX_OPEN_TRADES_REACHED.

**Steps:**
1. Create a BUY order for a symbol
2. Trigger another BUY alert while order is still open
3. Check Monitor tab → Blocked messages

**Expected:**
- Order creation blocked before attempt
- If blocked at guardrail level, should see MAX_OPEN_TRADES_REACHED

### Scenario 4: Force Buy Attempt but Make Exchange Fail → FAIL with Reason Code
**Steps:**
1. Set trade_enabled=True and trade_amount_usd for a symbol
2. Set a very small amount (below minimum notional) OR
3. Configure invalid API credentials OR
4. Use a symbol with insufficient balance

**Expected:**
- Buy attempt is made
- Exchange rejects with error
- Entry appears in blocked/throttled list
- Decision: FAILED
- Reason Code: Appropriate code (MIN_NOTIONAL_NOT_MET, AUTHENTICATION_ERROR, INSUFFICIENT_FUNDS, etc.)
- Reason Message: Human-readable description
- Exchange Error Snippet: Raw exchange error
- Context JSON includes: symbol, price, amount_usd, use_margin, leverage, etc.
- **Telegram failure message is sent** with:
  - Symbol
  - Reason code
  - Reason message
  - Exchange error summary

### Scenario 5: Missing Data → SKIP with DATA_MISSING
**Note:** This may be handled differently. The system should record a reason if data is missing.

**Steps:**
1. Create a symbol with missing price or indicator data
2. Trigger a BUY alert
3. Check Monitor tab → Blocked messages

**Expected:**
- Alert/order blocked if data missing
- Decision: SKIPPED
- Reason Code: DATA_MISSING or appropriate code
- Context includes which data is missing

## Testing Checklist

- [ ] Run database migration: `psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql`
- [ ] Verify migration created new columns
- [ ] Test Scenario 1: Trade disabled
- [ ] Test Scenario 2: Cooldown active
- [ ] Test Scenario 3: Max open orders
- [ ] Test Scenario 4: Exchange failure
- [ ] Test Scenario 5: Missing data
- [ ] Verify Monitor UI displays all fields correctly
- [ ] Verify expandable details show context JSON
- [ ] Verify correlation_id is generated and displayed
- [ ] Verify Telegram failure notifications are sent for FAILED decisions
- [ ] Verify no manual refresh needed (automatic polling works)

## Acceptance Criteria Status

✅ **A) Every alert in blocked/throttle has reason_code and reason_message**
- All guard clauses now create DecisionReason with both fields
- Alert blocking path now includes DecisionReason

✅ **B) Trade flag NO shows TRADE_DISABLED with field name and value**
- Implemented in `_create_buy_order()` trade_enabled check
- Context includes trade_enabled=False

✅ **C) Bot skip decisions show exact guard condition with numeric values**
- Max open orders: Shows current/max (e.g., "3/3")
- Cooldown: Shows remaining seconds/minutes
- Balance: Shows available/required
- All numeric values in context JSON

✅ **D) Buy failures appear in blocked/throttle with FAIL decision + Telegram notification**
- ORDER_FAILED events now include DecisionReason
- Telegram notification is sent with failure details
- Exchange error snippet is included

✅ **E) Monitor shows reasons without manual refresh**
- Uses existing polling mechanism (refreshInterval)
- New fields appear automatically in blocked messages

## Known Limitations / Future Enhancements

1. **Alert Blocking Reasons:** Alert blocking (when `should_emit_signal()` returns False) now records DecisionReason, but the reason_code mapping could be enhanced to better classify throttle reasons.

2. **More Guard Clauses:** Some guard clauses in the main monitoring loop (before `_create_buy_order()` is called) could also record DecisionReason. Currently, these are recorded when they occur inside `_create_buy_order()`.

3. **Correlation ID Propagation:** Correlation IDs are generated in each guard clause/failure handler. For better traceability, a single correlation_id could be generated at the start of the alert evaluation and passed through all decision points.

4. **Context Enhancement:** Some context fields could be enhanced with more detailed information (e.g., RSI values, MA values, etc. for strategy-related skips).

## Deployment Steps

1. **Backend:**
   - Run database migration: `psql -U trader -d atp -f backend/migrations/add_decision_tracing_fields.sql`
   - Deploy backend code
   - Verify no errors in logs

2. **Frontend:**
   - Deploy frontend code
   - Verify Monitor tab displays new fields
   - Test expandable details dropdown

3. **Verification:**
   - Run test scenarios above
   - Check Monitor UI for blocked messages
   - Verify all reasons are populated
   - Check Telegram notifications for failures

