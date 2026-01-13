# Minimal Patch Set - Lifecycle Event Emission Fixes

**Date:** 2026-01-02  
**Purpose:** Exact files changed + summaries for lifecycle event emission fixes

---

## Summary

This document lists the minimal set of changes required to ensure all lifecycle events are properly emitted to the throttle system (`SignalThrottleState`) and monitoring UI (`TelegramMessage`).

---

## Files Changed

### 1. `backend/app/services/signal_monitor.py`

**Changes:**
1. **Added helper function** `_emit_lifecycle_event()` (lines ~42-150)
   - Emits events to both `SignalThrottleState` (via `record_signal_event()`) and `TelegramMessage` (via `add_telegram_message()`)
   - Supports event types: `TRADE_BLOCKED`, `ORDER_CREATED`, `ORDER_FAILED`, `SLTP_CREATED`, `SLTP_FAILED`

2. **Add TRADE_BLOCKED event** in `_create_buy_order()` (after line ~3789)
   ```python
   if not getattr(watchlist_item, 'trade_enabled', False):
       _emit_lifecycle_event(
           db=db,
           symbol=symbol,
           strategy_key=strategy_key,
           side="BUY",
           price=current_price,
           event_type="TRADE_BLOCKED",
           event_reason="SKIP_DISABLED_TRADE",
       )
       return {"error": "trade_disabled", ...}
   ```

3. **Add TRADE_BLOCKED event** for invalid trade_amount_usd (after line ~3797)
   ```python
   if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
       _emit_lifecycle_event(
           db=db,
           symbol=symbol,
           strategy_key=strategy_key,
           side="BUY",
           price=current_price,
           event_type="TRADE_BLOCKED",
           event_reason="SKIP_INVALID_TRADE_AMOUNT",
           error_message=f"trade_amount_usd={watchlist_item.trade_amount_usd}",
       )
       raise ValueError(...)
   ```

4. **Add ORDER_CREATED event** after successful order creation (after line ~4505)
   ```python
   # After telegram_notifier.send_order_created() succeeds
   _emit_lifecycle_event(
       db=db,
       symbol=symbol,
       strategy_key=strategy_key,
       side="BUY",
       price=filled_price or current_price,
       event_type="ORDER_CREATED",
       event_reason=f"order_id={order_id}",
       order_id=str(order_id),
   )
   ```

5. **Add ORDER_FAILED event** when order placement fails (after line ~4430)
   ```python
   if not result or "error" in result:
       _emit_lifecycle_event(
           db=db,
           symbol=symbol,
           strategy_key=strategy_key,
           side="BUY",
           price=current_price,
           event_type="ORDER_FAILED",
           event_reason="order_placement_failed",
           error_message=error_msg,
       )
       return None
   ```

6. **Add SLTP_CREATED event** after successful SL/TP creation (after line ~4863)
   ```python
   # After SL/TP orders created successfully
   _emit_lifecycle_event(
       db=db,
       symbol=symbol,
       strategy_key=strategy_key,
       side="BUY",
       price=executed_avg_price,
       event_type="SLTP_CREATED",
       event_reason=f"primary_order_id={order_id}",
       order_id=str(order_id),
       sl_order_id=str(sl_order_id) if sl_order_id else None,
       tp_order_id=str(tp_order_id) if tp_order_id else None,
   )
   ```

7. **Add SLTP_FAILED event** when SL/TP creation fails (after line ~4879)
   ```python
   except Exception as sl_tp_err:
       error_msg = str(sl_tp_err)
       _emit_lifecycle_event(
           db=db,
           symbol=symbol,
           strategy_key=strategy_key,
           side="BUY",
           price=executed_avg_price,
           event_type="SLTP_FAILED",
           event_reason="sltp_creation_failed",
           order_id=str(order_id),
           error_message=error_msg,
       )
       # ... existing error handling ...
   ```

8. **Repeat same pattern for SELL orders** in `_create_sell_order()`:
   - TRADE_BLOCKED events (lines ~5084-5120)
   - ORDER_CREATED event (after line ~5316)
   - ORDER_FAILED event (after line ~5300)
   - SLTP_CREATED event (after line ~5650)
   - SLTP_FAILED event (after line ~5659)

**Summary:** ~15 locations updated to emit lifecycle events consistently.

---

### 2. `backend/app/services/exchange_sync.py`

**Changes:**
1. **Add SLTP_CREATED event** in `_create_sl_tp_for_filled_order()` after successful creation (after line ~1200)
   ```python
   # After SL and TP orders created successfully
   from app.services.signal_monitor import _emit_lifecycle_event
   from app.services.strategy_profiles import resolve_strategy_profile, build_strategy_key
   
   # Resolve strategy for event emission
   strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
   strategy_key = build_strategy_key(strategy_type, risk_approach)
   
   _emit_lifecycle_event(
       db=db,
       symbol=symbol,
       strategy_key=strategy_key,
       side=side,
       price=filled_price,
       event_type="SLTP_CREATED",
       event_reason=f"primary_order_id={order_id}",
       order_id=str(order_id),
       sl_order_id=str(sl_result.get("order_id")) if sl_result and sl_result.get("order_id") else None,
       tp_order_id=str(tp_result.get("order_id")) if tp_result and tp_result.get("order_id") else None,
   )
   ```

2. **Add SLTP_FAILED event** when SL/TP creation fails (after line ~1300)
   ```python
   except Exception as create_err:
       error_msg = str(create_err)
       _emit_lifecycle_event(
           db=db,
           symbol=symbol,
           strategy_key=strategy_key,
           side=side,
           price=filled_price,
           event_type="SLTP_FAILED",
           event_reason="sltp_creation_failed",
           order_id=str(order_id),
           error_message=error_msg,
       )
       # ... existing error handling ...
   ```

**Summary:** ~2 locations updated.

---

## Verification

After applying these changes, verify:

1. **TRADE_BLOCKED events appear in throttle:**
   ```bash
   # Check SignalThrottleState table
   SELECT symbol, side, emit_reason, last_time 
   FROM signal_throttle_states 
   WHERE emit_reason LIKE 'TRADE_BLOCKED%' 
   ORDER BY last_time DESC LIMIT 10;
   ```

2. **ORDER_CREATED events appear in throttle:**
   ```bash
   SELECT symbol, side, emit_reason, last_time 
   FROM signal_throttle_states 
   WHERE emit_reason LIKE 'ORDER_CREATED%' 
   ORDER BY last_time DESC LIMIT 10;
   ```

3. **ORDER_FAILED events appear in throttle:**
   ```bash
   SELECT symbol, side, emit_reason, last_time 
   FROM signal_throttle_states 
   WHERE emit_reason LIKE 'ORDER_FAILED%' 
   ORDER BY last_time DESC LIMIT 10;
   ```

4. **SLTP_CREATED events appear in throttle:**
   ```bash
   SELECT symbol, side, emit_reason, last_time 
   FROM signal_throttle_states 
   WHERE emit_reason LIKE 'SLTP_CREATED%' 
   ORDER BY last_time DESC LIMIT 10;
   ```

5. **SLTP_FAILED events appear in throttle:**
   ```bash
   SELECT symbol, side, emit_reason, last_time 
   FROM signal_throttle_states 
   WHERE emit_reason LIKE 'SLTP_FAILED%' 
   ORDER BY last_time DESC LIMIT 10;
   ```

6. **Events appear in Monitoring/Throttle tab:**
   - Navigate to `/api/monitoring/telegram-messages`
   - Verify events appear with correct `throttle_status` and `throttle_reason`

---

## Testing

1. **Test TRADE_BLOCKED:**
   - Set `trade_enabled=False` for a coin
   - Trigger a BUY signal
   - Verify `TRADE_BLOCKED` event is emitted

2. **Test ORDER_CREATED:**
   - Set `trade_enabled=True` and valid `trade_amount_usd`
   - Trigger a BUY signal
   - Verify `ORDER_CREATED` event is emitted after order placement

3. **Test ORDER_FAILED:**
   - Set insufficient balance or invalid order parameters
   - Trigger a BUY signal
   - Verify `ORDER_FAILED` event is emitted

4. **Test SLTP_CREATED:**
   - Create a successful BUY order
   - Verify `SLTP_CREATED` event is emitted after SL/TP creation

5. **Test SLTP_FAILED:**
   - Simulate SL/TP creation failure (e.g., invalid parameters)
   - Verify `SLTP_FAILED` event is emitted

---

## Impact Assessment

**Files Changed:** 2
- `backend/app/services/signal_monitor.py` (~15 locations)
- `backend/app/services/exchange_sync.py` (~2 locations)

**Lines Added:** ~200 lines (mostly helper function + event calls)
**Lines Modified:** ~0 lines (only additions, no deletions)

**Risk Level:** 🟢 **LOW**
- Only adds event emissions
- Does not modify existing logic
- Backward compatible (existing behavior unchanged)

**Dependencies:** None (uses existing functions)

---

**END OF MINIMAL PATCH SET**





