# BUY SIGNAL Decision Tracing Fix - Summary

## Problem Statement

BUY SIGNAL messages were being created and sent to Telegram/Monitor, but:
1. Orders were not being created after BUY SIGNAL (even though documentation says they must)
2. Decision tracing fields (`decision_type`, `reason_code`, `reason_message`) were NULL in the database
3. This indicated the buy-decision pipeline was not being executed or not instrumented properly

## Root Cause Analysis

### Pipeline Flow (Before Fix)

```
Market Update → BUY Signal Detected → Telegram Alert Sent → [GAP] → Order Creation Decision
                                                                    ↑
                                                          Decision tracing NOT written to original message
```

**Key Issues:**
1. BUY SIGNAL message created at line 2496 (`send_buy_signal`) → stored in DB without decision tracing
2. Order creation decision happens later (line 2971+) → creates NEW messages via `_emit_lifecycle_event`
3. Original BUY SIGNAL message never updated with decision trace
4. If `should_create_order=False`, fallback existed but didn't update original message

## Solution Implemented

### A) Pipeline Mapping

**Actual Runtime Flow:**
```
Market Update (signal_monitor.py)
  ↓
BUY Signal Detected (line ~1590)
  ↓
Telegram Alert Sent (line 2496: send_buy_signal)
  ↓ [Message stored in DB without decision_type]
  ↓
Order Creation Decision (line 2971: if should_create_order)
  ↓
  ├─→ SKIPPED (guard clauses: MAX_OPEN_ORDERS, COOLDOWN, etc.)
  ├─→ ATTEMPTED → FAILED (exchange errors)
  └─→ EXECUTED (order created successfully)
```

**Service:** On AWS, the market updater runs `python3 run_updater.py` directly, which executes the signal monitor loop. This process handles both market data updates and signal detection/order creation.

### B) Decision Trace Always Written

**New Function:** `update_telegram_message_decision_trace()` in `routes_monitoring.py`

This function:
- Finds the most recent BUY SIGNAL message for a symbol (within 5 minutes)
- Updates it with decision tracing fields
- Ensures no BUY SIGNAL message remains with NULL decision_type

**Update Points:**
1. **Guard Clauses** (MAX_OPEN_ORDERS, RECENT_ORDERS_COOLDOWN) - now update original message
2. **Order Creation Success** (ORDER_CREATED) - updates with EXECUTED decision
3. **Order Creation Failure** (ORDER_FAILED) - updates with FAILED decision
4. **Fallback Safety Net** - if no guard_reason, emits DECISION_PIPELINE_NOT_CALLED

### C) New Decision Types and Reason Codes

**Added to `decision_reason.py`:**
- `DecisionType.EXECUTED` - Order was successfully created
- `ReasonCode.EXEC_ORDER_PLACED` - Order placed successfully
- `ReasonCode.DECISION_PIPELINE_NOT_CALLED` - Safety net for missing instrumentation
- `make_execute()` function - Creates EXECUTED decision reasons

### D) Diagnostics Endpoints

**GET `/api/diagnostics/recent-buy-signals?limit=20`**
- Returns recent BUY SIGNAL messages with their decision traces
- Shows which signals have NULL decision_type (should be none after fix)
- Includes: signal_id, timestamp, symbol, price, decision_type, reason_code, reason_message, order_id

**POST `/api/diagnostics/run-signal-order-test?symbol=XXX&dry_run=true`**
- Self-test endpoint that exercises the signal → order pipeline
- Safe by default (dry_run=true)
- Returns structured report showing which steps passed/failed
- Can be used in production without SSH access

### E) AWS Profile Verification

**Confirmed:** `market-updater-aws` service is included in AWS profile:
```yaml
market-updater-aws:
  profiles:
    - aws
  command: python3 run_updater.py
  environment:
    - RUNTIME_ORIGIN=AWS
    - LIVE_TRADING=${LIVE_TRADING:-true}
```

The service runs when using `docker compose --profile aws up`.

## Files Changed

1. **backend/app/api/routes_monitoring.py**
   - Added `update_telegram_message_decision_trace()` function
   - Added `get_recent_buy_signals()` endpoint
   - Added `run_signal_order_test()` endpoint
   - Modified `add_telegram_message()` to return message_id

2. **backend/app/services/signal_monitor.py**
   - Updated guard clauses (MAX_OPEN_ORDERS, RECENT_ORDERS_COOLDOWN) to update original BUY SIGNAL message
   - Updated ORDER_CREATED handler to update original message with EXECUTED decision
   - Updated ORDER_FAILED handler to update original message with FAILED decision
   - Enhanced fallback safety net to update original message

3. **backend/app/utils/decision_reason.py**
   - Added `DecisionType.EXECUTED`
   - Added `ReasonCode.EXEC_ORDER_PLACED`
   - Added `ReasonCode.DECISION_PIPELINE_NOT_CALLED`
   - Added `make_execute()` function

## Decision Trace States

Every BUY SIGNAL must now have one of:

1. **SKIPPED** - Order was not attempted
   - `reason_code`: MAX_OPEN_TRADES_REACHED, RECENT_ORDERS_COOLDOWN, TRADE_DISABLED, etc.
   - `reason_message`: Human-readable explanation
   - `context_json`: Structured data (counts, timestamps, etc.)

2. **FAILED** - Order was attempted but failed
   - `reason_code`: EXCHANGE_REJECTED, INSUFFICIENT_FUNDS, AUTHENTICATION_ERROR, etc.
   - `reason_message`: Human-readable explanation
   - `exchange_error_snippet`: Raw exchange error message
   - `context_json`: Structured data

3. **EXECUTED** - Order was successfully created
   - `reason_code`: EXEC_ORDER_PLACED
   - `reason_message`: Success message with order_id
   - `context_json`: Contains order_id, exchange_order_id, price, quantity

4. **Safety Net** - If pipeline didn't run
   - `reason_code`: DECISION_PIPELINE_NOT_CALLED
   - `reason_message`: "BUY SIGNAL emitted but order pipeline did not run"

## Testing

### Local Testing
```bash
# 1. Check recent buy signals
curl http://localhost:8000/api/diagnostics/recent-buy-signals?limit=10

# 2. Run self-test
curl -X POST "http://localhost:8000/api/diagnostics/run-signal-order-test?symbol=DOT_USDT&dry_run=true"
```

### Production Testing on AWS (No SSH Required)
```bash
# Replace with your AWS server URL/domain
AWS_SERVER="your-aws-server-ip-or-domain"

# 1. Check recent buy signals
curl http://${AWS_SERVER}:8000/api/diagnostics/recent-buy-signals?limit=10

# 2. Run self-test via API
curl -X POST "http://${AWS_SERVER}:8000/api/diagnostics/run-signal-order-test?dry_run=true"
```

**Note:** If using nginx reverse proxy, use your domain instead:
```bash
curl https://your-domain.com/api/diagnostics/recent-buy-signals?limit=10
```

### Verification Checklist
- [ ] Every BUY SIGNAL message has non-NULL `decision_type`
- [ ] SKIPPED signals have `reason_code` and `reason_message`
- [ ] FAILED signals have `exchange_error_snippet`
- [ ] EXECUTED signals have `order_id` in `context_json`
- [ ] No signals with `decision_type=NULL` appear after fix deployment

## What Was Broken

1. **Decoupled Alert and Order Paths**: BUY SIGNAL alerts were sent, but order creation decision happened separately without updating the original message
2. **Missing Instrumentation**: Decision tracing was written to NEW messages via `_emit_lifecycle_event`, but original BUY SIGNAL message was never updated
3. **No Safety Net**: If decision pipeline didn't run, no trace was left behind

## What Is Fixed

1. **Unified Decision Tracing**: Original BUY SIGNAL message is now updated with decision trace in all cases
2. **Complete Coverage**: All paths (SKIPPED, FAILED, EXECUTED) now update the original message
3. **Safety Net**: If pipeline doesn't run, DECISION_PIPELINE_NOT_CALLED is recorded
4. **Diagnostics**: New endpoints allow verification without SSH access
5. **Self-Test**: Automated test endpoint exercises the full pipeline

## Next Steps

1. **Deploy to AWS**: 
   - For direct Python deployment: Deploy the updated backend code files
   - The market-updater process (running `python3 run_updater.py`) will automatically use the new code
   - The backend API process (running `python3 -m uvicorn app.main:app`) will automatically use the new code
   - Both processes share the same codebase, so deploying the files updates both
   
2. **Restart Services** (if needed):
   ```bash
   # On AWS server, restart the market-updater process
   # (method depends on how you're running it - systemd, screen, nohup, etc.)
   ```

3. **Monitor**: Use `/api/diagnostics/recent-buy-signals` to verify no NULL decision_type
   ```bash
   curl http://your-aws-server:8000/api/diagnostics/recent-buy-signals?limit=10
   ```

4. **Verify Orders**: Check that orders are actually being created when `should_create_order=True`
5. **Check Logs**: Look for `[DECISION]` log entries to trace decision flow

## Pipeline Diagram (After Fix)

```
Market Update
  ↓
BUY Signal Detected
  ↓
send_buy_signal() → Telegram Alert → DB: telegram_messages (decision_type=NULL initially)
  ↓
Order Creation Decision
  ↓
  ├─→ Guard Clauses Check
  │   ├─→ MAX_OPEN_ORDERS → update_telegram_message_decision_trace(SKIPPED)
  │   └─→ COOLDOWN → update_telegram_message_decision_trace(SKIPPED)
  │
  ├─→ Order Creation Attempt
  │   ├─→ SUCCESS → update_telegram_message_decision_trace(EXECUTED)
  │   └─→ FAILURE → update_telegram_message_decision_trace(FAILED)
  │
  └─→ Fallback (if no decision) → update_telegram_message_decision_trace(SKIPPED, DECISION_PIPELINE_NOT_CALLED)

Result: Every BUY SIGNAL message has decision_type, reason_code, reason_message
```

## Reason Codes Reference

### SKIPPED Reasons
- `MAX_OPEN_TRADES_REACHED` - Too many open positions
- `RECENT_ORDERS_COOLDOWN` - Order within last 5 minutes
- `TRADE_DISABLED` - trade_enabled=False
- `ALERT_DISABLED` - alert_enabled=False
- `DATA_MISSING` - Required MAs missing
- `GUARDRAIL_BLOCKED` - Portfolio value limit exceeded
- `INSUFFICIENT_AVAILABLE_BALANCE` - Not enough balance
- `IDEMPOTENCY_BLOCKED` - Duplicate order in same minute
- `DECISION_PIPELINE_NOT_CALLED` - Safety net (pipeline didn't run)

### FAILED Reasons
- `EXCHANGE_REJECTED` - Exchange rejected order
- `INSUFFICIENT_FUNDS` - Insufficient funds error
- `AUTHENTICATION_ERROR` - Auth failed
- `RATE_LIMIT` - Rate limited
- `TIMEOUT` - Request timeout
- `EXCHANGE_ERROR_UNKNOWN` - Unknown exchange error

### EXECUTED Reasons
- `EXEC_ORDER_PLACED` - Order successfully placed


