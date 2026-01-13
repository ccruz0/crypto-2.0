# Root-Cause Catalog - System Audit

**Date:** 2026-01-02  
**Purpose:** Catalog of all inconsistencies found between code, documentation, and expected behavior

---

## Summary

This document catalogs all inconsistencies found during the exhaustive end-to-end audit. Each entry includes:
- **File path + line references**
- **Severity** (breaks trading, breaks UI, docs-only)
- **Recommended fix**

---

## 1. Missing Event Emissions

### 1.1 TRADE_BLOCKED Events Not Emitted to Throttle

**Issue:** When trade gates block order creation, the system logs to console and sends Telegram messages, but does NOT emit structured `TRADE_BLOCKED` events to the throttle system (`SignalThrottleState`).

**Location:**
- `backend/app/services/signal_monitor.py:3782-3812` (`_create_buy_order()`)
- `backend/app/services/signal_monitor.py:5084-5120` (`_create_sell_order()`)

**Current Behavior:**
- Trade gates check `trade_enabled`, `trade_amount_usd`, max orders, etc.
- If blocked: Logs warning, sends Telegram (sometimes), returns `None`
- **Missing:** No `record_signal_event()` call with `TRADE_BLOCKED` reason

**Expected Behavior (Source of Truth):**
- Emit `TRADE_BLOCKED` event to throttle with:
  - `symbol`, `side`, `gate_name`, `reason`, `timestamp`
  - Record to `SignalThrottleState` with `trade_decision=SKIP` and `trade_reason=<gate_name>`

**Severity:** 🔴 **BREAKS TRADING** - Cannot audit why trades were blocked

**Recommended Fix:**
```python
# In _create_buy_order() and _create_sell_order(), after gate checks fail:
if not trade_enabled:
    record_signal_event(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",  # or "SELL"
        price=current_price,
        source="trade_gate",
        emit_reason=f"TRADE_BLOCKED: SKIP_DISABLED_TRADE"
    )
    # Also add to throttle message system
    from app.api.routes_monitoring import add_telegram_message
    add_telegram_message(
        f"🚫 TRADE BLOCKED: {symbol} {side} - trade_enabled=False",
        symbol=symbol,
        blocked=True,
        throttle_status="TRADE_BLOCKED",
        throttle_reason="SKIP_DISABLED_TRADE"
    )
```

---

### 1.2 ORDER_FAILED Events Not Emitted to Throttle

**Issue:** When order placement fails (exchange API error, insufficient balance, etc.), the system sends Telegram notifications but does NOT emit structured `ORDER_FAILED` events to throttle.

**Location:**
- `backend/app/services/signal_monitor.py:4430-4477` (BUY order failure)
- `backend/app/services/signal_monitor.py:5300-5350` (SELL order failure)

**Current Behavior:**
- On failure: Sends Telegram error notification, logs error, returns `None`
- **Missing:** No `record_signal_event()` call with `ORDER_FAILED` reason

**Expected Behavior (Source of Truth):**
- Emit `ORDER_FAILED` event to throttle with:
  - `symbol`, `side`, `order_id` (if available), `error`, `timestamp`
  - Record to `SignalThrottleState` with `order_created=False` and `error_message=<error>`

**Severity:** 🔴 **BREAKS TRADING** - Cannot audit order failures

**Recommended Fix:**
```python
# After order placement fails:
record_signal_event(
    db=db,
    symbol=symbol,
    strategy_key=strategy_key,
    side="BUY",  # or "SELL"
    price=current_price,
    source="order_placement",
    emit_reason=f"ORDER_FAILED: {error_msg}"
)
# Also add to throttle message system
add_telegram_message(
    f"❌ ORDER FAILED: {symbol} {side} - {error_msg}",
    symbol=symbol,
    blocked=False,
    order_failed=True,
    error_message=error_msg
)
```

---

### 1.3 SLTP_FAILED Events Not Emitted to Throttle

**Issue:** When SL/TP creation fails, the system sends CRITICAL Telegram alerts but does NOT emit structured `SLTP_FAILED` events to throttle.

**Location:**
- `backend/app/services/signal_monitor.py:4879-4920` (BUY SL/TP failure)
- `backend/app/services/signal_monitor.py:5650-5700` (SELL SL/TP failure)
- `backend/app/services/exchange_sync.py:745-1310` (`_create_sl_tp_for_filled_order()`)

**Current Behavior:**
- On failure: Sends CRITICAL Telegram alert, logs error
- **Missing:** No `record_signal_event()` call with `SLTP_FAILED` reason

**Expected Behavior (Source of Truth):**
- Emit `SLTP_FAILED` event to throttle with:
  - `symbol`, `side`, `primary_order_id`, `error`, `timestamp`
  - Record to `SignalThrottleState` with `sltp_created=False` and `error_message=<error>`

**Severity:** 🔴 **BREAKS TRADING** - Cannot audit SL/TP failures

**Recommended Fix:**
```python
# After SL/TP creation fails:
record_signal_event(
    db=db,
    symbol=symbol,
    strategy_key=strategy_key,
    side="BUY",  # or "SELL"
    price=filled_price,
    source="sltp_creation",
    emit_reason=f"SLTP_FAILED: {error_msg}"
)
# Also add to throttle message system
add_telegram_message(
    f"🚨 SLTP_FAILED: {symbol} {side} - {error_msg}",
    symbol=symbol,
    blocked=False,
    sltp_failed=True,
    error_message=error_msg
)
```

---

### 1.4 ORDER_CREATED Events Not Emitted to Throttle

**Issue:** When orders are created successfully, the system sends Telegram notifications but does NOT emit structured `ORDER_CREATED` events to throttle.

**Location:**
- `backend/app/services/signal_monitor.py:4505-4523` (BUY order created)
- `backend/app/services/signal_monitor.py:5316-5334` (SELL order created)

**Current Behavior:**
- On success: Sends Telegram notification, saves to database
- **Missing:** No `record_signal_event()` call with `ORDER_CREATED` reason

**Expected Behavior (Source of Truth):**
- Emit `ORDER_CREATED` event to throttle with:
  - `symbol`, `side`, `order_id`, `price`, `quantity`, `timestamp`
  - Record to `SignalThrottleState` with `order_created=True` and `order_id=<id>`

**Severity:** 🟡 **BREAKS UI** - Throttle tab cannot show order creation events

**Recommended Fix:**
```python
# After order created successfully:
record_signal_event(
    db=db,
    symbol=symbol,
    strategy_key=strategy_key,
    side="BUY",  # or "SELL"
    price=filled_price or current_price,
    source="order_creation",
    emit_reason=f"ORDER_CREATED: order_id={order_id}"
)
# Also add to throttle message system
add_telegram_message(
    f"✅ ORDER_CREATED: {symbol} {side} - order_id={order_id}",
    symbol=symbol,
    blocked=False,
    order_created=True,
    order_id=order_id
)
```

---

### 1.5 SLTP_CREATED Events Not Emitted to Throttle

**Issue:** When SL/TP orders are created successfully, the system sends Telegram notifications but does NOT emit structured `SLTP_CREATED` events to throttle.

**Location:**
- `backend/app/services/signal_monitor.py:4863-4875` (BUY SL/TP created)
- `backend/app/services/exchange_sync.py:745-1310` (`_create_sl_tp_for_filled_order()`)

**Current Behavior:**
- On success: Sends Telegram notification with SL/TP order IDs
- **Missing:** No `record_signal_event()` call with `SLTP_CREATED` reason

**Expected Behavior (Source of Truth):**
- Emit `SLTP_CREATED` event to throttle with:
  - `symbol`, `side`, `primary_order_id`, `sl_order_id`, `tp_order_id`, `timestamp`
  - Record to `SignalThrottleState` with `sltp_created=True` and order IDs

**Severity:** 🟡 **BREAKS UI** - Throttle tab cannot show SL/TP creation events

**Recommended Fix:**
```python
# After SL/TP created successfully:
record_signal_event(
    db=db,
    symbol=symbol,
    strategy_key=strategy_key,
    side="BUY",  # or "SELL"
    price=filled_price,
    source="sltp_creation",
    emit_reason=f"SLTP_CREATED: sl_id={sl_order_id}, tp_id={tp_order_id}"
)
# Also add to throttle message system
add_telegram_message(
    f"✅ SLTP_CREATED: {symbol} {side} - SL={sl_order_id}, TP={tp_order_id}",
    symbol=symbol,
    blocked=False,
    sltp_created=True,
    sl_order_id=sl_order_id,
    tp_order_id=tp_order_id
)
```

---

## 2. UI Tab Data Inconsistencies

### 2.1 Executed Orders Tab Missing Canceled Orders

**Issue:** The Executed Orders tab may not include canceled orders, or includes them inconsistently.

**Location:**
- `backend/app/api/routes_orders.py` (executed orders endpoint)

**Current Behavior:**
- Executed Orders endpoint filters by status `FILLED`
- **Missing:** Canceled orders (`CANCELLED` status) may not be included

**Expected Behavior (Source of Truth):**
- Executed Orders tab must include:
  - All orders with status `FILLED` OR `CANCELLED`
  - Both primary orders AND SL/TP orders

**Severity:** 🟡 **BREAKS UI** - Users cannot see canceled orders

**Recommended Fix:**
```python
# In get_executed_orders() endpoint:
executed_orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.status.in_([OrderStatusEnum.FILLED, OrderStatusEnum.CANCELLED])
).all()
```

---

### 2.2 Open Orders Tab Missing SL/TP Orders

**Issue:** The Open Orders tab may not consistently include SL/TP orders.

**Location:**
- `backend/app/api/routes_orders.py` (open orders endpoint)

**Current Behavior:**
- Open Orders endpoint filters by status `NEW`, `ACTIVE`, `PARTIALLY_FILLED`
- **Unclear:** Whether SL/TP orders are included

**Expected Behavior (Source of Truth):**
- Open Orders tab must include:
  - All orders with status `NEW`, `ACTIVE`, `PARTIALLY_FILLED`
  - Both primary orders AND SL/TP orders

**Severity:** 🟡 **BREAKS UI** - Users cannot see active SL/TP orders

**Recommended Fix:**
```python
# In get_open_orders() endpoint:
open_orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
).all()
# Ensure SL/TP orders are included (no filter by order_role or order_type)
```

---

### 2.3 Throttle Tab Data Source Inconsistency

**Issue:** The Throttle tab uses `TelegramMessage` table instead of `SignalThrottleState` table, causing inconsistencies.

**Location:**
- `backend/app/api/routes_monitoring.py` (`get_telegram_messages()`)

**Current Behavior:**
- Throttle tab reads from `TelegramMessage` table (parsed from Telegram messages)
- **Problem:** Not all events are sent to Telegram (e.g., TRADE_BLOCKED, ORDER_FAILED)
- **Problem:** Parsing Telegram messages is error-prone

**Expected Behavior (Source of Truth):**
- Throttle tab should read from `SignalThrottleState` table (canonical source)
- All events should be recorded to `SignalThrottleState` via `record_signal_event()`

**Severity:** 🟡 **BREAKS UI** - Throttle tab shows incomplete/inaccurate data

**Recommended Fix:**
```python
# Create new endpoint: /api/monitoring/throttle-events
# Read from SignalThrottleState table directly
throttle_events = db.query(SignalThrottleState).filter(
    SignalThrottleState.last_time >= since_time
).order_by(SignalThrottleState.last_time.desc()).all()
```

---

## 3. Documentation Inconsistencies

### 3.1 Missing Decision Gates Documentation

**Issue:** No comprehensive documentation listing all decision gates and their exact behavior.

**Location:**
- `docs/` directory
- `README.md` files

**Current Behavior:**
- Documentation mentions some gates but not all
- Gate names in docs don't match code exactly

**Expected Behavior (Source of Truth):**
- Documentation must list ALL gates with:
  - Exact gate name (as in code)
  - What it checks
  - What message is emitted when it blocks
  - Location in code

**Severity:** 🟢 **DOCS ONLY** - Makes debugging harder

**Recommended Fix:**
- Add "Decision Gates" section to `docs/SYSTEM_MAP.md` (already created)
- Update all README files to reference `docs/SYSTEM_MAP.md`

---

### 3.2 Missing Coin & Strategy Config Documentation

**Issue:** No clear documentation on how to add a new coin or configure strategy parameters.

**Location:**
- `docs/` directory
- `README.md` files

**Current Behavior:**
- Documentation mentions coins and strategies but not how to configure them

**Expected Behavior (Source of Truth):**
- Documentation must include:
  - Where parameters live (watchlist table, trading_config.json)
  - Examples for at least 2 coins
  - How to add a new coin safely

**Severity:** 🟢 **DOCS ONLY** - Makes onboarding harder

**Recommended Fix:**
- Add "Coin & Strategy Config" section to `docs/SYSTEM_MAP.md` (already created)
- Add examples for BTC_USDT and SOL_USDT

---

### 3.3 Lifecycle Documentation Mismatch

**Issue:** Documentation doesn't match the exact lifecycle in code.

**Location:**
- `docs/` directory
- `README.md` files

**Current Behavior:**
- Documentation describes a simplified lifecycle
- Missing phases (e.g., polling for fill confirmation, SL/TP creation timing)

**Expected Behavior (Source of Truth):**
- Documentation must match `docs/SYSTEM_MAP.md` exactly (already created)

**Severity:** 🟢 **DOCS ONLY** - Misleads developers

**Recommended Fix:**
- Update all lifecycle documentation to reference `docs/SYSTEM_MAP.md`
- Remove outdated lifecycle descriptions

---

## 4. Code Inconsistencies

### 4.1 Silent Failures in Order Lifecycle

**Issue:** Some failures are logged but not emitted as events, making them "silent" from an audit perspective.

**Location:**
- `backend/app/services/signal_monitor.py` (multiple locations)
- `backend/app/services/exchange_sync.py` (SL/TP creation)

**Current Behavior:**
- Failures log to console/logs
- **Missing:** Not all failures emit structured events to throttle

**Expected Behavior (Source of Truth):**
- All failures must emit structured events:
  - `TRADE_BLOCKED` for gate failures
  - `ORDER_FAILED` for order placement failures
  - `SLTP_FAILED` for SL/TP creation failures

**Severity:** 🔴 **BREAKS TRADING** - Cannot audit failures

**Recommended Fix:**
- Add event emissions for all failure paths (see sections 1.1-1.5)

---

### 4.2 Inconsistent Event Emission Patterns

**Issue:** Some events are emitted via `record_signal_event()`, others via `add_telegram_message()`, causing inconsistency.

**Location:**
- `backend/app/services/signal_monitor.py` (throughout)

**Current Behavior:**
- Alert events: Use `record_signal_event()` + `add_telegram_message()`
- Order events: Use `add_telegram_message()` only (missing `record_signal_event()`)
- Block events: Use `add_telegram_message()` only (missing `record_signal_event()`)

**Expected Behavior (Source of Truth):**
- ALL events must use BOTH:
  - `record_signal_event()` → `SignalThrottleState` (canonical source)
  - `add_telegram_message()` → `TelegramMessage` (for UI display)

**Severity:** 🟡 **BREAKS UI** - Inconsistent data sources

**Recommended Fix:**
- Standardize all event emissions to use both functions
- Create helper function: `emit_lifecycle_event()` that calls both

---

## 5. Missing Test Coverage

### 5.1 No Lifecycle Integration Tests

**Issue:** No tests verify the complete lifecycle from signal → alert → gate → order → SL/TP → events.

**Location:**
- `backend/app/tests/` directory

**Current Behavior:**
- Unit tests exist for individual components
- **Missing:** End-to-end lifecycle tests

**Expected Behavior (Source of Truth):**
- Tests must cover:
  - Signal → alerts emitted when enabled
  - When gate blocks: no order attempt, but TRADE_BLOCKED emitted
  - When gate allows and exchange responds success: ORDER_CREATED then SLTP_ATTEMPT triggered
  - When exchange fails: ORDER_FAILED emitted and chain stops
  - When order canceled: appears in executed/canceled list

**Severity:** 🟡 **BREAKS TESTING** - Cannot verify lifecycle correctness

**Recommended Fix:**
- Create `test_lifecycle_integration.py` with mock exchange adapter
- Test all phases of lifecycle

---

## 6. Summary Table

| Issue | Severity | Location | Status |
|-------|----------|----------|--------|
| TRADE_BLOCKED events missing | 🔴 BREAKS TRADING | `signal_monitor.py:3782-3812` | ❌ Not Fixed |
| ORDER_FAILED events missing | 🔴 BREAKS TRADING | `signal_monitor.py:4430-4477` | ❌ Not Fixed |
| SLTP_FAILED events missing | 🔴 BREAKS TRADING | `signal_monitor.py:4879-4920` | ❌ Not Fixed |
| ORDER_CREATED events missing | 🟡 BREAKS UI | `signal_monitor.py:4505-4523` | ❌ Not Fixed |
| SLTP_CREATED events missing | 🟡 BREAKS UI | `signal_monitor.py:4863-4875` | ❌ Not Fixed |
| Executed Orders missing canceled | 🟡 BREAKS UI | `routes_orders.py` | ❓ Needs Verification |
| Open Orders missing SL/TP | 🟡 BREAKS UI | `routes_orders.py` | ❓ Needs Verification |
| Throttle tab data source | 🟡 BREAKS UI | `routes_monitoring.py` | ❌ Not Fixed |
| Missing gates documentation | 🟢 DOCS ONLY | `docs/` | ✅ Fixed (SYSTEM_MAP.md) |
| Missing config documentation | 🟢 DOCS ONLY | `docs/` | ✅ Fixed (SYSTEM_MAP.md) |
| Lifecycle docs mismatch | 🟢 DOCS ONLY | `docs/` | ✅ Fixed (SYSTEM_MAP.md) |
| Silent failures | 🔴 BREAKS TRADING | Multiple | ❌ Not Fixed |
| Inconsistent event patterns | 🟡 BREAKS UI | `signal_monitor.py` | ❌ Not Fixed |
| Missing lifecycle tests | 🟡 BREAKS TESTING | `tests/` | ❌ Not Fixed |

---

**END OF ROOT-CAUSE CATALOG**





