# Fallback Decision Tracing Fix

## Problem

Alerts are being sent successfully (e.g., TRX_USDT BUY at 03:41:19, SOL_USDT SELL at 03:55:08), but:
- ❌ No order is created
- ❌ No decision tracing is recorded (decision_type, reason_code are NULL)

## Root Cause

Decision tracing is emitted in guard clauses (MAX_OPEN_ORDERS, RECENT_ORDERS_COOLDOWN), but:
1. If `_emit_lifecycle_event` fails silently (caught by try/except), no decision is recorded
2. If guard clauses don't execute (early return or exception), no decision is recorded
3. There was no fallback mechanism to ensure decision tracing is always recorded

## Solution

Added a **fallback decision tracing mechanism** in the `else` clause when `should_create_order=False`:

### When Fallback Triggers

- `buy_alert_sent_successfully=True` (alert was sent)
- `should_create_order=False` (order was blocked)
- `guard_reason` is set (e.g., "MAX_OPEN_ORDERS" or "RECENT_ORDERS_COOLDOWN")

### What Fallback Does

1. Creates a fallback `DecisionReason` with:
   - `reason_code`: `MAX_OPEN_TRADES_REACHED` or `RECENT_ORDERS_COOLDOWN` (based on guard_reason)
   - `reason_message`: "Order blocked for {symbol} after alert was sent. Guard reason: {guard_reason}"
   - `context`: Includes symbol, guard_reason, price, and `fallback: True` flag
   - `source`: "guardrail_fallback"

2. Emits `TRADE_BLOCKED` event with the fallback decision

3. Logs a warning so we know the fallback was used

## Code Location

`backend/app/services/signal_monitor.py` lines 3630-3667

## Impact

**Before:**
- Alert sent → Order blocked → ❌ No decision tracing (if guard clauses fail)
- Monitor UI shows alert but no explanation

**After:**
- Alert sent → Order blocked → ✅ Fallback decision tracing ensures we always have a record
- Monitor UI shows alert AND blocked entry with decision details

## Notes

- **SELL orders**: SELL signals also create automatic orders when `trade_enabled=True`. Decision tracing applies to both BUY and SELL orders. The fallback mechanism works for both order types.

- **Primary decision tracing**: Still emitted in guard clauses (lines 2803-2925). Fallback is a safety net.

- **Fallback flag**: The `fallback: True` flag in context helps identify when fallback was used vs. primary decision tracing.

## Testing

After deployment:
1. Wait for next BUY alert that gets blocked
2. Check Monitor UI → Telegram (Mensajes Bloqueados)
3. Should see blocked entry with decision_type, reason_code, reason_message
4. Check logs for "⚠️ {symbol}: BUY alert sent but emitting fallback decision tracing" warnings

---

**Status:** ✅ Complete and deployed  
**Date:** 2026-01-09

