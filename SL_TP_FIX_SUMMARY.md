# SL/TP Order Creation Fix - Summary

## Problem
SL/TP orders were not created after SELL orders because the code assumed MARKET orders fill immediately. In reality, MARKET orders may settle asynchronously, so the initial response may not have `status=FILLED` or `cumulative_quantity` (executed quantity) available yet.

## Root Cause
1. Code checked `is_filled || has_avg_price` and assumed immediate fills
2. Used requested quantity (`qty`) as fallback when `cumulative_quantity` was not available
3. Did not poll for fill confirmation
4. Did not normalize quantity to exchange rules
5. Silent failures - only logged warnings, no CRITICAL alerts

## Solution Implemented

### 1. Fill Confirmation Polling
- Added `_poll_order_fill_confirmation()` helper function
- Polls exchange (get_open_orders + get_order_history) until order is confirmed FILLED
- Configurable: up to 10 attempts with 1s sleep (default)

### 2. Executed Quantity Usage
- Always uses `cumulative_quantity` from filled order
- NEVER uses requested quantity (`qty`) as fallback
- Validates `cumulative_quantity > 0` before proceeding

### 3. Quantity Normalization
- Uses `normalize_quantity()` helper to ensure exchange compliance
- Rounds DOWN to stepSize (qty_tick_size)
- Enforces minQty (minimum quantity)
- Formats to exact quantity_decimals decimal places

### 4. CRITICAL Alerts
- Sends CRITICAL Telegram alerts when:
  - Executed quantity is invalid
  - Quantity normalization fails
  - SL/TP creation fails
- Alerts include: symbol, order_id, quantities, error details
- Warning: "Position is UNPROTECTED"

### 5. Failsafe Configuration
- Environment variable: `FAILSAFE_ON_SLTP_ERROR` (default: `true`)
- Enables additional safety actions on failure

## Files Changed

**`backend/app/services/signal_monitor.py`**
- Added configuration constants (lines 53-56)
- Added `_poll_order_fill_confirmation()` helper (lines 4607-4721)
- Updated `_create_sell_order()` with fill confirmation and normalization (lines 5101-5268)
- Added comprehensive inline documentation

**Total changes:** +363 lines, -30 lines

## Configuration

```bash
# Order fill confirmation polling
ORDER_FILL_POLL_MAX_ATTEMPTS=10          # Default: 10
ORDER_FILL_POLL_INTERVAL_SECONDS=1.0     # Default: 1.0

# Failsafe behavior
FAILSAFE_ON_SLTP_ERROR=true              # Default: true
```

## New Flow

```
1. Place SELL MARKET order -> get order_id
2. Check initial response: if status=FILLED AND cumulative_quantity > 0, use it
3. If not filled: Poll exchange until status=FILLED (up to 10 attempts)
4. Extract EXECUTED quantity (cumulative_quantity) - NEVER use requested qty
5. Normalize quantity using normalize_quantity() helper
6. Create SL/TP with normalized executed quantity
7. If SL/TP fails: Send CRITICAL Telegram alert + log error
```

## Testing

### Verify the Fix
1. Place a SELL order and monitor logs for:
   - `[FILL_CONFIRMATION]` messages showing polling attempts
   - `[SL/TP]` messages showing normalized quantity
   - CRITICAL alerts if SL/TP fails
2. Check Telegram for alerts
3. Verify SL/TP orders are created with correct (normalized) quantity

### Key Log Messages to Look For
- `✅ [SL/TP] Order {order_id} already FILLED in initial response`
- `🔄 [SL/TP] Order {order_id} not immediately FILLED... Polling for fill confirmation...`
- `✅ [FILL_CONFIRMATION] Order {order_id} confirmed FILLED on attempt {N}`
- `✅ [SL/TP] Quantity normalized: raw={X} -> normalized={Y}`
- `❌ [SL/TP] CRITICAL: Failed to create SL/TP orders...`

## Documentation

- **Detailed fix documentation:** `docs/SL_TP_FILL_CONFIRMATION_FIX.md`
- **Inline code comments:** Comprehensive documentation in `signal_monitor.py`
- **Exchange docs:** `docs/trading/crypto_com_order_formatting.md`

## Status

✅ **COMPLETE**

All requirements met:
- ✅ Fill confirmation polling before SL/TP placement
- ✅ Uses executed quantity, never requested quantity
- ✅ Quantity normalization to exchange rules
- ✅ CRITICAL alerts on failure (no silent failures)
- ✅ Failsafe configuration option
- ✅ Comprehensive logging and documentation

**Result:** SL/TP orders are now created reliably with correct quantities, and failures are impossible to miss.




