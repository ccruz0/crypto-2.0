# Alert to Order Flow - Invariant Enforcement

## Invariant

**If the system sends a BUY or SELL signal to Telegram OR records it as "sent" in the Signal Throttle panel, it MUST immediately attempt to place the corresponding live order (BUY or SELL) with no extra eligibility checks.**

The ONLY allowed check before placing is **DEDUPLICATION** (prevent duplicates).

Everything else (RSI thresholds, MA checks, volume checks, cooldowns, alert_enabled flags, trade_enabled flags) must happen **BEFORE** the message is considered "sent".

If a message is "sent", then order placement must happen right after, always.

## Sequence Diagram

```
Market Updater
    ↓
Signal Detection (calculate_trading_signals)
    ↓
Throttle Check (should_emit_signal) - time/price gates
    ↓
[ALL ELIGIBILITY CHECKS - BEFORE "sent"]
    ├─ alert_enabled check
    ├─ buy_alert_enabled / sell_alert_enabled check
    ├─ trade_enabled check
    ├─ trade_amount_usd validation
    ├─ MAX_OPEN_ORDERS check
    ├─ RECENT_ORDERS_COOLDOWN check
    ├─ LIVE_TRADING check
    └─ Portfolio value limit check
    ↓
[IF ALL PASS]
    ↓
Mark as "SENT" (send_buy_signal + record_signal_event)
    ↓
[DEDUP CHECK - ONLY CHECK AFTER "sent"]
    ├─ Check idempotency_key in DB
    └─ If duplicate exists → SKIP order, log reason
    ↓
[IF NOT DUPLICATE]
    ↓
Place Order (_create_buy_order)
    ↓
Order Result
    ├─ SUCCESS → ORDER_CREATED event
    └─ FAILURE → ORDER_FAILED event (with reason)
```

## Where Throttle Happens

Throttle (time/price gates) happens in `should_emit_signal()` in `signal_throttle.py`:
- **Time gate**: Fixed 60 seconds cooldown per (symbol, side, strategy)
- **Price gate**: Minimum price change % (configurable per symbol)

Throttle is checked **BEFORE** marking as "sent".

## Where Order Placement Happens

Order placement happens in `_create_buy_order()` in `signal_monitor.py`:
- Called immediately after marking as "sent"
- Only dedup check can block it after "sent"

## Dedup Key Definition

**Idempotency Key Format**: `{env}:{symbol}:{side}:{signal_timestamp_bucket}:{strategy_id}`

Where:
- `env`: Environment (e.g., "AWS", "LOCAL")
- `symbol`: Trading symbol (e.g., "BTC_USDT")
- `side`: Order side ("BUY" or "SELL")
- `signal_timestamp_bucket`: Minute-level bucket (e.g., "2024-01-01T12:34:00")
- `strategy_id`: Strategy key (e.g., "swing:conservative")

**Storage**: Checked in `ExchangeOrder` table by querying for orders with same symbol, side, and timestamp bucket (minute-level).

**Logic**: If an order with the same idempotency key exists in the last 24 hours, skip order placement but still log the attempt.

## LIVE_TRADING=false Handling

If `LIVE_TRADING=false`:
- Alert is still sent (informational)
- Order is NOT placed
- Lifecycle event: `ORDER_BLOCKED_LIVE_TRADING`
- Decision trace: `SKIPPED` with `reason_code=ORDER_BLOCKED_LIVE_TRADING`

This ensures the alert is sent but clearly indicates no order was placed due to LIVE_TRADING being disabled.

## Safety Switches

1. **Kill Switch**: If enabled, all signal processing is skipped (no alerts, no orders)
2. **LIVE_TRADING**: If false, alerts sent but orders blocked (with clear lifecycle event)
3. **alert_enabled**: Master switch for alerts (if false, no alerts, no orders)
4. **trade_enabled**: If false, alerts may be sent but orders are blocked

## Decision Tracing

Every BUY/SELL signal that is "sent" must have a decision trace:
- **SKIPPED**: Order was not attempted (reason: guardrail, LIVE_TRADING=false, etc.)
- **FAILED**: Order was attempted but failed (reason: exchange error, insufficient balance, etc.)
- **EXECUTED**: Order was placed successfully (order_id recorded)

Decision traces are stored in `TelegramMessage` table:
- `decision_type`: "SKIPPED", "FAILED", or "EXECUTED"
- `reason_code`: Canonical reason code (e.g., "MAX_OPEN_TRADES_REACHED", "ORDER_BLOCKED_LIVE_TRADING")
- `reason_message`: Human-readable reason
- `context_json`: Additional context (order_id, error details, etc.)

## Implementation Notes

The orchestrator function `_orchestrate_buy_signal_with_order()` ensures:
1. All eligibility checks happen BEFORE marking as "sent"
2. If all checks pass → mark as "sent" → immediately attempt order
3. Only dedup check happens after "sent" but before order
4. LIVE_TRADING=false is handled explicitly with clear lifecycle event
