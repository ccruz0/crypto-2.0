# Decision Tracing: Guard Clauses Fix

## Problem Identified

When testing TRX_USDT alert:
- ✅ Alert was sent successfully
- ❌ Order was NOT created
- ❌ **No decision reason was recorded** - this was the gap!

## Root Cause

Multiple guard clauses in the order creation path were blocking orders but **not emitting decision tracing events**. When an alert was sent but order creation was blocked, there was no record of WHY the order wasn't created.

## Solution

Added decision tracing to **all guard clauses** that can block order creation:

### 1. Order Creation Lock Check (Line ~2753)
- **Reason Code:** `ORDER_CREATION_LOCK`
- **When:** Order creation lock is active (prevents duplicate concurrent orders)
- **Context:** Lock age, timeout seconds

### 2. Max Open Orders Check - Initial (Line ~2775)
- **Reason Code:** `MAX_OPEN_TRADES_REACHED`
- **When:** Unified open positions >= MAX_OPEN_ORDERS_PER_SYMBOL
- **Context:** Open positions count, max limit, symbol

### 3. Recent Orders Cooldown - Initial (Line ~2782)
- **Reason Code:** `RECENT_ORDERS_COOLDOWN`
- **When:** Recent BUY orders found within 5 minutes
- **Context:** Recent orders count, time since last order, order IDs

### 4. Recent Orders Cooldown - Final Check (Line ~2897)
- **Reason Code:** `RECENT_ORDERS_COOLDOWN`
- **When:** Final check finds recent orders (race condition protection)
- **Context:** Recent orders count, seconds remaining, check type

### 5. Max Open Orders Check - Final (Line ~2971)
- **Reason Code:** `MAX_OPEN_TRADES_REACHED`
- **When:** Final check exceeds max open orders (race condition detected)
- **Context:** Open positions, max limit, check type

### 6. Idempotency Check (Line ~2956)
- **Reason Code:** `IDEMPOTENCY_BLOCKED`
- **When:** Order already exists for this signal_key (minute-level bucket)
- **Context:** Signal key, existing order ID

### 7. Alert Enabled Check (Line ~3001)
- **Reason Code:** `ALERT_DISABLED`
- **When:** alert_enabled=False (final check before order creation)
- **Context:** alert_enabled status, trade_enabled status

### 8. Missing MAs Check (Line ~3012)
- **Reason Code:** `DATA_MISSING`
- **When:** Required technical indicators (MA50/EMA10) are missing
- **Context:** Missing indicators list, available MAs

### 9. Portfolio Value Limit (Line ~3043)
- **Reason Code:** `GUARDRAIL_BLOCKED`
- **When:** Portfolio value > 3x trade_amount_usd (over-concentration protection)
- **Context:** Portfolio value, limit value, net quantity

### 10. Safety Guard - Position Count Failed (Line ~2891)
- **Reason Code:** `SAFETY_GUARD`
- **When:** Cannot verify open positions count (conservative block)
- **Context:** Error details, check type

## New Reason Codes Added

Added to `ReasonCode` enum:
- `ORDER_CREATION_LOCK`
- `IDEMPOTENCY_BLOCKED`
- `ALERTS_DISABLED` (added as alias for ALERT_DISABLED)

## Impact

**Before:**
- Alert sent → Order blocked → ❌ No reason recorded
- Monitor UI shows alert but no explanation for missing order

**After:**
- Alert sent → Order blocked → ✅ Reason recorded with full context
- Monitor UI shows alert AND blocked entry with decision details

## Testing

After deployment:
1. Clear throttle state for TRX_USDT
2. Wait for next alert
3. Check Monitor UI → Telegram (Mensajes Bloqueados)
4. Should see blocked entry with:
   - Decision Type: SKIPPED
   - Reason Code: (one of the guard clause reasons)
   - Reason Message: Detailed explanation
   - Context JSON: Full context data

## Files Changed

- `backend/app/services/signal_monitor.py` - Added decision tracing to 10 guard clauses
- `backend/app/utils/decision_reason.py` - Added missing reason codes

---

**Status:** ✅ Complete and deployed  
**Date:** 2026-01-09

