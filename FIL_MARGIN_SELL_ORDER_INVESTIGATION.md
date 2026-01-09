# FIL Margin SELL Order Investigation

## Problem

FIL_USDT SELL order with margin enabled (`MARGIN:YES`) failed with error 306 (INSUFFICIENT_AVAILABLE_BALANCE) even though margin trading should allow shorting.

**Telegram Message:**
```
❌ AUTOMATIC SELL ORDER CREATION FAILED

📊 Symbol: FIL_USDT
🔴 Side: SELL
💰 Amount: $10.00
📦 Quantity: 6.55909747
❌ Error: 500 Server Error: INSUFFICIENT_AVAILABLE_BALANCE (code: 306)
```

## Configuration Check

**Watchlist Items:**
- Row 1: `trade_enabled=true`, `trade_amount_usd=10`, `trade_on_margin=true`, `sell_alert_enabled=true`, `alert_enabled=true`
- Row 2: `trade_enabled=false`, `trade_on_margin=false`, `sell_alert_enabled=false`, `alert_enabled=false`

**Issue:** Duplicate rows - one enabled, one disabled. Code should use the enabled one.

## Root Cause Analysis

### 1. Early Balance Check (Line ~3820-3880)
- **Status:** ✅ Already skips balance check for margin orders
- **Code:** `if not user_wants_margin_check:` (line 3828)
- **Conclusion:** Early balance check should not block margin orders

### 2. Order Creation Check (Line ~4002-4005)
- **Status:** ⚠️ Checks `balance_check_warning` but should be None for margin orders
- **Code:** `if balance_check_warning:` (line 4005) → skips order creation
- **Conclusion:** If `balance_check_warning` is set for margin orders, this is a bug

### 3. Error 306 Retry Logic (Line ~6260-6400)
- **Status:** ✅ Now added (just fixed)
- **Code:** Leverage reduction retry + SPOT fallback
- **Conclusion:** Should now retry with reduced leverage and SPOT fallback

## Fixes Applied

1. ✅ **Error 306 Retry Logic for SELL Orders** (Commit 75ffbfa)
   - Added leverage reduction retry
   - Added SPOT fallback
   - Added decision tracing

2. ⚠️ **Early Balance Check** - Already skips for margin orders, but may have issue with duplicate rows

## Next Steps

1. **Verify duplicate rows are not causing issues**
   - Check if code is using correct watchlist_item (enabled one)
   - Consider removing duplicate rows or adding unique constraint

2. **Wait for next FIL_USDT SELL alert**
   - Monitor logs for order creation attempt
   - Check if error 306 retry logic works
   - Verify decision tracing is recorded

3. **Test with FIL_USDT**
   - Ensure only one watchlist_item row (enabled one)
   - Clear throttle state
   - Wait for SELL signal
   - Verify order is created or retry logic triggers

## Expected Behavior After Fix

When margin SELL order fails with error 306:
1. ✅ System tries with reduced leverage (e.g., 5x → 3x → 1x)
2. ✅ If that fails, tries SPOT fallback (if base currency balance available)
3. ✅ Emits decision tracing with full context
4. ✅ Monitor UI shows decision details

## Current Status

- ✅ Error 306 retry logic added for SELL orders
- ✅ Decision tracing added for SELL order failures
- ⚠️ Duplicate watchlist_item rows need investigation
- ⚠️ Early balance check may need verification with duplicate rows

---

**Status:** ✅ Fixes deployed, waiting for next alert to verify  
**Date:** 2026-01-09  
**Commits:** 75ffbfa (error 306 retry), d9173c9 (documentation)

