# SELL Margin Error 306 Fix

## Problem

SELL orders with margin enabled (`MARGIN:YES`) were failing immediately with error 306 (INSUFFICIENT_AVAILABLE_BALANCE) without attempting retries or fallbacks.

**Example:**
- FIL_USDT SELL order with margin enabled
- Error: `500 Server Error: INSUFFICIENT_AVAILABLE_BALANCE (code: 306)`
- Order failed immediately, no retry attempts

## Root Cause

SELL orders were missing the error 306 retry logic that BUY orders have. When a margin SELL order failed with error 306:
- ❌ No leverage reduction retry
- ❌ No SPOT fallback attempt
- ❌ Immediate failure

BUY orders had this logic (lines 5028-5227), but SELL orders did not (lines 6185-6254).

## Solution

Added the same error 306 retry logic to SELL orders that BUY orders have:

### 1. Leverage Reduction Retry
When margin SELL order fails with error 306:
1. Record the failure in leverage cache
2. Try with reduced leverage (e.g., 5x → 3x → 1x)
3. If retry succeeds, use the successful result
4. If retry also fails with 306, try even lower leverage

### 2. SPOT Fallback
If all leverage retries fail:
1. Check available base currency balance (e.g., FIL for FIL_USDT)
2. If sufficient balance, try SPOT order (no margin)
3. If SPOT succeeds, use the successful result

### 3. Decision Tracing
All failure scenarios now emit decision tracing:
- Authentication errors → `AUTHENTICATION_ERROR`
- Error 306 after all retries → `INSUFFICIENT_FUNDS` or `EXCHANGE_REJECTED`
- Full context includes: symbol, side, amount, leverage attempts, fallback attempts

## Code Changes

**File:** `backend/app/services/signal_monitor.py`

**Location:** `_create_sell_order` function (lines ~6185-6400)

**Added:**
- Error 306 detection and leverage reduction retry logic
- SPOT fallback for SELL orders (checks base currency balance)
- Decision tracing for all failure scenarios
- Proper error message aggregation across retry attempts

## Expected Behavior

**Before:**
- Margin SELL order fails with 306 → ❌ Immediate failure, no retry

**After:**
- Margin SELL order fails with 306 → ✅ Try reduced leverage → ✅ Try SPOT fallback → ✅ Success or proper error with decision tracing

## Testing

After deployment, test with a margin SELL order:
1. Ensure symbol has `MARGIN:YES` enabled
2. Trigger SELL signal
3. If error 306 occurs, system should:
   - Try with reduced leverage
   - If that fails, try SPOT (if base currency balance available)
   - Emit decision tracing with full context

## Notes

- **Base Currency Balance:** For SELL orders, SPOT fallback checks base currency balance (e.g., FIL), not quote currency (USDT)
- **Leverage Cache:** Failed leverage attempts are cached to avoid repeating failed leverage levels
- **Decision Tracing:** All failure scenarios now have proper decision tracing for Monitor UI visibility

---

**Status:** ✅ Fixed and deployed  
**Date:** 2026-01-09  
**Commit:** 75ffbfa

