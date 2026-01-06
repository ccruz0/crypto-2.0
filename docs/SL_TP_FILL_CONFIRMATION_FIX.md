# SL/TP Order Creation Fix - Fill Confirmation

**Date:** 2026-01-02  
**Issue:** SL/TP orders were not created after SELL orders because the code assumed immediate fills  
**Status:** ✅ Fixed

---

## Root Cause Analysis

### Problem
After placing a SELL MARKET order, the code attempted to create SL/TP orders immediately. However, MARKET orders may settle asynchronously, meaning:
1. The initial response may not have `status=FILLED`
2. The `cumulative_quantity` (executed quantity) may not be available yet
3. The code would skip SL/TP creation or use the wrong quantity (requested instead of executed)

### Previous Code Flow (Broken)
```
1. Place SELL order -> get order_id
2. Check: is_filled OR has_avg_price
3. If true: Use cumulative_quantity OR fallback to requested qty
4. Create SL/TP with that quantity
5. If fails: Log warning (silent failure)
```

**Issues:**
- ❌ Assumed immediate fills
- ❌ Used requested quantity as fallback (incorrect)
- ❌ No polling for fill confirmation
- ❌ No quantity normalization
- ❌ Silent failures (only warnings)

---

## Fix Implementation

### New Code Flow (Fixed)
```
1. Place SELL order -> get order_id
2. Check initial response: if status=FILLED AND cumulative_quantity > 0, use it
3. If not filled: Poll exchange (get_open_orders + get_order_history)
   - Up to 10 attempts with 1s sleep (configurable)
   - Stop when status=FILLED AND cumulative_quantity > 0
4. Extract EXECUTED quantity (cumulative_quantity) - NEVER use requested qty
5. Normalize quantity using normalize_quantity() helper:
   - Round DOWN to stepSize (qty_tick_size)
   - Enforce minQty (minimum quantity)
   - Format to exact quantity_decimals decimal places
6. Create SL/TP with normalized executed quantity
7. If SL/TP fails: Send CRITICAL Telegram alert + log error
```

### Key Changes

#### 1. Fill Confirmation Polling (`_poll_order_fill_confirmation`)
- **Location:** `backend/app/services/signal_monitor.py:4607`
- **Function:** Polls exchange until order is confirmed FILLED with executed quantity
- **Implementation:**
  - Checks `get_open_orders()` first (order might still be open)
  - Falls back to `get_order_history()` (order might be filled and closed)
  - Configurable: `ORDER_FILL_POLL_MAX_ATTEMPTS` (default: 10)
  - Configurable: `ORDER_FILL_POLL_INTERVAL_SECONDS` (default: 1.0)
  - Returns `None` if not filled after max attempts

#### 2. Executed Quantity Usage
- **Location:** `backend/app/services/signal_monitor.py:5177-5230`
- **Change:** Always uses `cumulative_quantity` from filled order, never requested `qty`
- **Validation:** Ensures `cumulative_quantity > 0` before proceeding

#### 3. Quantity Normalization
- **Location:** `backend/app/services/signal_monitor.py:5190-5205`
- **Function:** Uses `trade_client.normalize_quantity()` helper
- **Purpose:** Ensures quantity matches exchange precision rules:
  - Rounds DOWN to stepSize
  - Enforces minQty
  - Formats to exact decimal places
- **Reference:** `docs/trading/crypto_com_order_formatting.md`

#### 4. CRITICAL Alerts on Failure
- **Location:** `backend/app/services/signal_monitor.py:5207-5268`
- **Change:** Sends CRITICAL Telegram alerts when:
  - Executed quantity is invalid
  - Quantity normalization fails
  - SL/TP creation fails
- **Alert Content:**
  - Symbol, order_id, side
  - Raw quantity, normalized quantity
  - Error message
  - Warning: "Position is UNPROTECTED"

#### 5. Failsafe Configuration
- **Location:** `backend/app/services/signal_monitor.py:53-56`
- **Environment Variable:** `FAILSAFE_ON_SLTP_ERROR` (default: `true`)
- **Purpose:** Enables additional safety actions when SL/TP fails (currently logs warning, extensible for future safety measures)

---

## Files Modified

### `backend/app/services/signal_monitor.py`
- **Lines 53-56:** Added configuration for polling and failsafe
- **Lines 4607-4721:** Added `_poll_order_fill_confirmation()` helper function
- **Lines 5101-5268:** Updated `_create_sell_order()` to use fill confirmation and normalization
- **Documentation:** Added comprehensive inline comments explaining the flow

---

## Configuration

### Environment Variables

```bash
# Order fill confirmation polling
ORDER_FILL_POLL_MAX_ATTEMPTS=10          # Max attempts to poll for fill (default: 10)
ORDER_FILL_POLL_INTERVAL_SECONDS=1.0     # Seconds between polls (default: 1.0)

# Failsafe behavior
FAILSAFE_ON_SLTP_ERROR=true              # Enable failsafe on SL/TP error (default: true)
```

---

## Testing Recommendations

### Unit Tests
- Test `_poll_order_fill_confirmation()` with:
  - Immediately filled orders
  - Delayed fills (multiple polling attempts)
  - Orders not found after max attempts
  - Invalid responses from exchange

### Integration Tests
- Test full SELL order flow:
  1. Place SELL order
  2. Verify polling behavior
  3. Verify quantity normalization
  4. Verify SL/TP creation with normalized quantity
  5. Verify CRITICAL alerts on failure

### Manual Testing
1. Place a SELL order and monitor logs for:
   - `[FILL_CONFIRMATION]` log messages
   - `[SL/TP]` log messages showing normalized quantity
   - CRITICAL alerts if SL/TP fails
2. Check Telegram for alerts
3. Verify SL/TP orders are created with correct (normalized) quantity

---

## Exchange Documentation References

- **Crypto.com Exchange API:** `private/create-order` (MARKET orders)
- **Order Status Lifecycle:** NEW -> ACTIVE -> FILLED (or CANCELLED)
- **Quantity Precision Rules:** See `docs/trading/crypto_com_order_formatting.md`
- **Key Points:**
  - `cumulative_quantity` only available when order is FILLED
  - Quantity must match `stepSize` (qty_tick_size)
  - Quantity must be >= `minQty`
  - Quantity must have exact `quantity_decimals` decimal places

---

## Rollback Plan

If issues arise, revert the changes to `backend/app/services/signal_monitor.py`:

```bash
git revert <commit-hash>
```

The previous behavior will be restored, but note that SL/TP may still fail silently for asynchronously-filled orders.

---

## Related Issues

- Original issue: SL/TP orders not created after SELL orders
- Root cause: Assumed immediate fills, used requested quantity instead of executed
- Impact: Positions left unprotected when SL/TP creation failed silently

---

## Summary

✅ **Fixed:** Fill confirmation polling ensures orders are FILLED before SL/TP creation  
✅ **Fixed:** Always uses executed quantity (cumulative_quantity), never requested  
✅ **Fixed:** Quantity normalization ensures exchange precision compliance  
✅ **Fixed:** CRITICAL alerts prevent silent failures  
✅ **Fixed:** Comprehensive logging and documentation

**Result:** SL/TP orders are now created reliably with correct quantities, and failures are impossible to miss.




