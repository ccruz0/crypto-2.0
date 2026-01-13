# Signal-to-Order Orchestrator Implementation

## Overview

This document describes the implementation of the signal-to-order orchestrator that ensures every BUY/SELL signal marked as "sent" triggers an immediate order attempt, with only deduplication as the safeguard.

## Business Rule

**If a BUY/SELL signal is sent to Telegram OR appears in throttle as sendable, it MUST trigger an order immediately.**
**No further eligibility checks/gates are allowed after signal emission. The ONLY safeguard is de-duplication.**

## Implementation

### 1. Order Intent Table

Created `order_intents` table for atomic deduplication:
- `idempotency_key`: UNIQUE constraint for atomic deduplication
- `signal_id`: Reference to telegram_messages.id
- `status`: PENDING, ORDER_PLACED, ORDER_FAILED, DEDUP_SKIPPED, ORDER_BLOCKED_LIVE_TRADING
- Created via migration script: `backend/scripts/create_order_intents_table.py`

### 2. Orchestrator Module

Created `backend/app/services/signal_order_orchestrator.py` with:
- `compute_idempotency_key()`: Computes deterministic key (prefers signal_id, falls back to content-hash + 60s bucket)
- `create_order_intent()`: Creates order intent with atomic deduplication (UNIQUE constraint)
- `update_order_intent_status()`: Updates order intent after order attempt

### 3. Integration in signal_monitor.py

The orchestrator is called immediately after `buy_alert_sent_successfully = True`:

```python
# After signal is sent
buy_alert_sent_successfully = True

# Call orchestrator
order_intent, intent_status = create_order_intent(db, signal_id, symbol, "BUY", message_content)

if intent_status == "DEDUP_SKIPPED":
    # Duplicate signal - record SKIPPED
elif intent_status == "ORDER_BLOCKED_LIVE_TRADING":
    # LIVE_TRADING=false - record SKIPPED
elif intent_status == "PENDING":
    # Order intent created - attempt order placement
    order_result = asyncio.run(self._create_buy_order(db, watchlist_item, current_price, res_up, res_down))
    # Update order_intent and decision trace
```

### 4. Decision Tracing

Every signal now has decision tracing populated:
- `decision_type`: SKIPPED, FAILED, EXECUTED
- `reason_code`: Canonical reason code
- `reason_message`: Human-readable message
- `context_json`: Contextual data
- `exchange_error_snippet`: Exchange error (for FAILED)

### 5. Pipeline Stages

Decision tracing tracks the pipeline:
1. **SIGNAL_SENT**: Signal sent to Telegram
2. **ORDER_REQUESTED**: Order intent created (or DEDUP_SKIPPED)
3. **ORDER_PLACED** / **ORDER_FAILED** / **DEDUP_SKIPPED**: Final outcome

## Files Changed

1. `backend/app/models/order_intent.py` - New model for order intents
2. `backend/app/services/signal_order_orchestrator.py` - Orchestrator module
3. `backend/app/services/signal_monitor.py` - Integration point (after signal sent)
4. `backend/app/api/routes_monitoring.py` - `add_telegram_message` now returns message ID
5. `backend/app/models/__init__.py` - Added OrderIntent export
6. `backend/scripts/create_order_intents_table.py` - Migration script

## Known Limitations

**CRITICAL**: The current implementation still calls `_create_buy_order()` which has eligibility checks (trade_enabled, trade_amount_usd, balance checks, etc.). 

According to the business rule, these checks should happen BEFORE signal generation, not after. The orchestrator integration ensures that:
- Deduplication is atomic (UNIQUE constraint)
- Decision tracing is always populated
- Order intent is created before order attempt

However, `_create_buy_order()` may still fail due to eligibility checks that should have been done before signal generation.

**Next Steps** (if needed):
- Move all eligibility checks (MAX_OPEN_ORDERS, RECENT_ORDERS_COOLDOWN, trade_enabled, etc.) to BEFORE signal generation
- Ensure `_create_buy_order()` only performs order creation (no eligibility checks) when called from orchestrator

## Testing

To test the orchestrator:

1. **Create table**:
   ```bash
   python backend/scripts/create_order_intents_table.py
   ```

2. **Trigger a BUY signal** (ensure conditions are met)
   - Signal should be sent to Telegram
   - Orchestrator should create order_intent
   - Order should be attempted
   - Decision tracing should be populated

3. **Test deduplication**:
   - Trigger the same signal twice (within 60s bucket)
   - First should create order_intent and attempt order
   - Second should return DEDUP_SKIPPED (no second exchange call)

4. **Verify decision tracing**:
   - Check `telegram_messages` table for `decision_type`, `reason_code`, `reason_message`
   - Check `order_intents` table for order intent records

## Database Schema

```sql
CREATE TABLE order_intents (
    id SERIAL PRIMARY KEY,
    idempotency_key VARCHAR(200) UNIQUE NOT NULL,
    signal_id INTEGER,
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    order_id VARCHAR(100),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX ix_order_intents_idempotency_key ON order_intents(idempotency_key);
CREATE INDEX ix_order_intents_signal_id ON order_intents(signal_id);
CREATE INDEX ix_order_intents_symbol_side ON order_intents(symbol, side);
```

## Reason Codes

- `IDEMPOTENCY_BLOCKED`: Duplicate signal (deduplicated)
- `ORDER_BLOCKED_LIVE_TRADING`: LIVE_TRADING=false (signal sent but order blocked)
- `EXEC_ORDER_PLACED`: Order created successfully
- `EXCHANGE_REJECTED`: Order creation failed (exchange error)
