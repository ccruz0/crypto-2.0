# Fix: ALGO Alert Missing Decision Tracing

## Problem

**ALGO_USDT BUY alert (ID 140759-140758) was sent but order was blocked** (ID 140760):
- ✅ Alert sent to Telegram (ID 140759)
- ❌ Order blocked: Portfolio value ($12146.82) exceeds limit (3x trade_amount = $30.00)
- ❌ **Missing decision tracing**: `decision_type`, `reason_code`, `reason_message` all NULL
- ❌ Message created with `blocked=False`, `order_skipped=True` (incorrect)

## Root Cause

After `_emit_lifecycle_event` creates a message with decision tracing (blocked=True, decision_type, reason_code, etc.), there were **duplicate `add_telegram_message` calls** that created messages **without** decision tracing:

1. **DATA_MISSING guard** (line 3319): Duplicate message after `_emit_lifecycle_event`
2. **PORTFOLIO_VALUE_LIMIT guard** (line 3378): Duplicate message after `_emit_lifecycle_event` ← **This is the ALGO case**
3. **TRADE_DISABLED guard** (line 3618): No decision tracing at all

These duplicate messages were showing up in the Monitor UI without decision tracing fields.

## Fix

### 1. Removed Duplicate Messages ✅
Removed duplicate `add_telegram_message` calls that created messages without decision tracing:
- Line 3319: DATA_MISSING guard
- Line 3378: PORTFOLIO_VALUE_LIMIT guard (ALGO case)
- Line 3618: TRADE_DISABLED guard

**Reason:** `_emit_lifecycle_event` already creates the message with full decision tracing (blocked=True, decision_type, reason_code, reason_message, context_json, exchange_error_snippet, correlation_id).

### 2. Added Decision Tracing for TRADE_DISABLED ✅
Added decision tracing for the `trade_enabled=False` case:
- Creates `DecisionReason` with `TRADE_DISABLED` reason code
- Emits `TRADE_BLOCKED` event with decision tracing
- Records full context (symbol, trade_enabled, alert_sent, price)

## Expected Behavior (After Fix)

When an alert is sent but order is blocked:

### Portfolio Value Limit (ALGO case):
1. ✅ Alert sent to Telegram
2. ✅ `_emit_lifecycle_event` creates message with:
   - `blocked=True`
   - `decision_type=SKIPPED`
   - `reason_code=GUARDRAIL_BLOCKED`
   - `reason_message`: "Portfolio value limit exceeded for ALGO_USDT. Portfolio value $12146.82 > limit $30.00 (3x trade_amount)."
   - `context_json`: Full context (portfolio_value, limit_value, trade_amount_usd, net_quantity, price)
3. ✅ **No duplicate message** created
4. ✅ Monitor UI shows decision details

### Trade Disabled:
1. ✅ Alert sent to Telegram
2. ✅ `_emit_lifecycle_event` creates message with:
   - `blocked=True`
   - `decision_type=SKIPPED`
   - `reason_code=TRADE_DISABLED`
   - `reason_message`: "Trade disabled for SYMBOL. Alert was sent but order will not be created because trade_enabled=False for this symbol."
   - `context_json`: Full context (symbol, trade_enabled, alert_sent, price)
3. ✅ Monitor UI shows decision details

### Data Missing:
1. ✅ Alert sent to Telegram
2. ✅ `_emit_lifecycle_event` creates message with:
   - `blocked=True`
   - `decision_type=SKIPPED`
   - `reason_code=DATA_MISSING`
   - `reason_message`: "Missing required indicators (MA50 or EMA10) for SYMBOL."
   - `context_json`: Full context (symbol, missing_indicators, price)
3. ✅ Monitor UI shows decision details

## Files Changed

- `backend/app/services/signal_monitor.py`:
  - Removed duplicate `add_telegram_message` calls (3 locations)
  - Added decision tracing for `trade_enabled=False` case
  - Total: 53 lines changed (30 insertions, 23 deletions)

## Testing

To verify the fix:

1. **Portfolio Value Limit Test:**
   - Trigger an alert for a symbol with portfolio value > 3x trade_amount
   - Verify Monitor UI shows `GUARDRAIL_BLOCKED` with full context

2. **Trade Disabled Test:**
   - Trigger an alert for a symbol with `trade_enabled=False`
   - Verify Monitor UI shows `TRADE_DISABLED` with full context

3. **Data Missing Test:**
   - Trigger an alert for a symbol with missing MA50/EMA10
   - Verify Monitor UI shows `DATA_MISSING` with full context

## Deployment

**Commit:** To be created  
**Status:** ✅ Ready for deployment  
**Testing:** Should be verified with next ALGO (or similar) alert that gets blocked

---

**Date:** 2026-01-09  
**Issue:** ALGO alert missing decision tracing  
**Fix:** Removed duplicate messages, added decision tracing for all guard clauses

