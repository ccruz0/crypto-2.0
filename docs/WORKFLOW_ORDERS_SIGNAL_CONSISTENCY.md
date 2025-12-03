# Orders-Signal Consistency Workflow

**Purpose:** Ensure that orders created by `SignalMonitorService` are consistent with the signals that triggered them.

**Status:** ✅ Ready for use

---

## Overview

This workflow validates that:
1. Orders are only created when signals match (BUY orders from BUY signals, SELL orders from SELL signals)
2. Order parameters (price, quantity, side) are consistent with signal evaluation
3. Order creation respects `trade_enabled` flag
4. Orders are not created when signals are WAIT
5. Order creation logic uses the same signal evaluation as alerts

---

## When to Use

Use this workflow when:
- Orders are being created but signals show WAIT
- BUY orders are created when SELL signals are active (or vice versa)
- Order prices/quantities don't match signal evaluation
- Orders are created when `trade_enabled=False`
- Need to verify order-signal alignment after code changes

---

## Validation Steps

### 1. Signal Evaluation Consistency

**Check:** Both alerts and orders use the same signal evaluation

**Files to inspect:**
- `backend/app/services/signal_monitor.py` - Order creation logic
- `backend/app/services/signal_evaluator.py` - Canonical signal evaluation

**Validation:**
```python
# Order creation should use the same evaluation result as alerts
eval_result = evaluate_signal_for_symbol(db, watchlist_item, symbol)

# Orders should only be created when:
# - Signal matches order side (BUY signal → BUY order, SELL signal → SELL order)
# - trade_enabled = True
# - trade_amount_usd > 0
if eval_result["decision"] == "BUY" and eval_result["can_emit_buy_alert"]:
    if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd > 0:
        # Create BUY order
```

**Log markers to check:**
- `[LIVE_ALERT_DECISION]` - Shows signal evaluation result
- `[LIVE_BUY_CALL]` / `[LIVE_SELL_CALL]` - Shows alert emission
- Order creation logs should reference the same `decision` and `can_emit_*` values

---

### 2. Order Side Validation

**Check:** Order side matches signal side

**Validation:**
- BUY orders should only be created when `decision="BUY"` and `buy_signal=True`
- SELL orders should only be created when `decision="SELL"` and `sell_signal=True`
- No orders should be created when `decision="WAIT"`

**Code location:**
- `SignalMonitorService._check_signal_for_coin_sync()` - Order creation section

**Expected pattern:**
```python
# BUY order creation
if buy_signal and can_emit_buy_alert:
    if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd > 0:
        # Create BUY order using current_price from signal evaluation

# SELL order creation  
if sell_signal and can_emit_sell_alert:
    if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd > 0:
        # Create SELL order using current_price from signal evaluation
```

---

### 3. Price Consistency

**Check:** Order price matches signal evaluation price

**Validation:**
- Order price should use the same `current_price` from `evaluate_signal_for_symbol()`
- Price should not be stale (should be from the same evaluation cycle)

**Code location:**
- `SignalMonitorService._create_buy_order()` / `_create_sell_order()`

**Expected pattern:**
```python
# Use price from canonical evaluation
eval_result = evaluate_signal_for_symbol(db, watchlist_item, symbol)
current_price = eval_result["price"]

# Order creation uses same price
order_result = asyncio.run(self._create_buy_order(
    db, watchlist_item, current_price, res_up, res_down
))
```

---

### 4. Trade Flag Validation

**Check:** Orders respect `trade_enabled` flag

**Validation:**
- Orders should NOT be created when `trade_enabled=False`
- Alerts should still be sent even when `trade_enabled=False` (alerts ≠ orders)

**Code location:**
- `SignalMonitorService._check_signal_for_coin_sync()` - Order creation section

**Expected pattern:**
```python
# Alert is sent regardless of trade_enabled
if can_emit_buy_alert:
    send_buy_signal(...)  # Always sent if signal conditions met

# Order is only created if trade_enabled=True
if can_emit_buy_alert and watchlist_item.trade_enabled and watchlist_item.trade_amount_usd > 0:
    create_buy_order(...)  # Only created if trade enabled
```

---

### 5. Signal-Order Timing Validation

**Check:** Orders are created in the same cycle as signal detection

**Validation:**
- Order creation should happen immediately after signal evaluation
- No delay between signal detection and order creation (same function call)

**Code location:**
- `SignalMonitorService._check_signal_for_coin_sync()` - Signal evaluation → Order creation flow

**Expected pattern:**
```python
# 1. Evaluate signal (canonical)
eval_result = evaluate_signal_for_symbol(db, watchlist_item, symbol)

# 2. Emit alert (if conditions met)
if eval_result["can_emit_buy_alert"]:
    send_buy_signal(...)

# 3. Create order (if trade enabled, same cycle)
if eval_result["can_emit_buy_alert"] and watchlist_item.trade_enabled:
    create_buy_order(...)  # Same cycle, same signal evaluation
```

---

## Audit Script

Create a script to validate orders-signal consistency:

```bash
#!/usr/bin/env bash
# scripts/audit_orders_signal_consistency.sh

echo "=== Orders-Signal Consistency Audit ==="

# 1. Check recent orders
echo "Recent orders (last 1 hour):"
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && \
  docker compose exec backend-aws python -c \"
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
from datetime import datetime, timedelta, timezone
db = SessionLocal()
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
orders = db.query(ExchangeOrder).filter(
    ExchangeOrder.created_at >= cutoff
).all()
for o in orders:
    print(f'{o.symbol} {o.side} @ {o.price} created={o.created_at}')
\""

# 2. Check signal evaluation for same symbols
echo ""
echo "Signal evaluation for symbols with recent orders:"
# (Run debug_live_signals_all.py and compare)
```

---

## Common Issues

### Issue 1: Orders Created When Signal is WAIT

**Symptoms:**
- Orders appear in database
- Signal evaluation shows `decision=WAIT` for same symbol

**Root Cause:**
- Order creation not checking signal evaluation result
- Stale signal state used for order creation

**Fix:**
- Ensure order creation uses `evaluate_signal_for_symbol()` result
- Don't create orders when `decision="WAIT"`

---

### Issue 2: BUY Orders from SELL Signals

**Symptoms:**
- SELL signal detected
- BUY order created (wrong side)

**Root Cause:**
- Order side not validated against signal side
- Signal state confusion

**Fix:**
- Validate `decision` and `buy_signal`/`sell_signal` before order creation
- Use same evaluation result for both alert and order

---

### Issue 3: Orders Created When trade_enabled=False

**Symptoms:**
- Orders created
- `trade_enabled=False` in watchlist

**Root Cause:**
- Missing `trade_enabled` check in order creation
- Flag not refreshed from database

**Fix:**
- Always check `watchlist_item.trade_enabled` before order creation
- Refresh watchlist item from database before order creation

---

### Issue 4: Price Mismatch

**Symptoms:**
- Order price differs from signal evaluation price
- Large price discrepancy

**Root Cause:**
- Using stale price
- Different price source for orders vs signals

**Fix:**
- Use same `current_price` from `evaluate_signal_for_symbol()`
- Don't fetch price separately for orders

---

## Verification Commands

### 1. Check Recent Orders vs Signals

```bash
# On AWS
docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py" | grep -E "SYMBOL|BUY|SELL"

# Check orders
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder
from datetime import datetime, timedelta, timezone
db = SessionLocal()
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
orders = db.query(ExchangeOrder).filter(ExchangeOrder.created_at >= cutoff).all()
for o in orders:
    print(f'{o.symbol} {o.side} @ {o.price} created={o.created_at}')
"
```

### 2. Check Signal Evaluation for Specific Symbol

```bash
# Run debug script and filter for symbol
docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py" | grep "SYMBOL_NAME"

# Check logs for that symbol
docker compose logs backend-aws | grep "SYMBOL_NAME" | grep -E "LIVE_ALERT_DECISION|order created|BUY order|SELL order"
```

### 3. Verify trade_enabled Flag

```bash
# Check watchlist item
docker compose exec backend-aws python -c "
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == 'SYMBOL_NAME').first()
if item:
    print(f'trade_enabled={item.trade_enabled}, trade_amount_usd={item.trade_amount_usd}')
"
```

---

## Integration with Other Workflows

This workflow complements:
- **Signal Evaluation Unification** (`docs/monitoring/SIGNAL_EVALUATION_UNIFICATION.md`) - Ensures signals are evaluated consistently
- **Backend Strategy & Alerts Audit** (`docs/WORKFLOW_BACKEND_STRATEGY_ALERTS_AUDIT.md`) - Validates backend logic
- **Full Integration Audit** (`docs/WORKFLOW_FULL_INTEGRATION_AUDIT.md`) - End-to-end validation

---

## Success Criteria

✅ **Orders-Signal Consistency is VALID when:**
1. All orders have matching signals (BUY orders from BUY signals, SELL orders from SELL signals)
2. No orders created when `decision="WAIT"`
3. No orders created when `trade_enabled=False`
4. Order prices match signal evaluation prices
5. Orders created in same cycle as signal detection
6. Order creation uses same `evaluate_signal_for_symbol()` result as alerts

---

## Related Documentation

- **Signal Flow Overview:** `docs/monitoring/signal_flow_overview.md`
- **Business Rules:** `docs/monitoring/business_rules_canonical.md`
- **Signal Evaluation Unification:** `docs/monitoring/SIGNAL_EVALUATION_UNIFICATION.md`
- **Portfolio Risk Refactor:** `docs/monitoring/portfolio_risk_refactor_summary.md` - Orders blocked by risk, alerts not blocked

