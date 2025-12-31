# TP Order Cancellation Fix

## Issue
When a STOP_LIMIT (SL) order is executed, the corresponding TAKE_PROFIT_LIMIT (TP) order should be automatically cancelled, but in some cases this was not happening.

**Example Case:**
- SL Order ID: `5755600481522118793` (STOP_LIMIT BUY) was executed
- TP Order ID: `5755600481522118913` should have been cancelled but wasn't

## Root Cause Analysis

### Bug Found: Missing OPEN Status in OCO Cancellation

The `_cancel_oco_sibling()` function was missing `OrderStatusEnum.OPEN` in its status filter. This meant that if a TP order was in `OPEN` status, it would not be found and cancelled when the SL order executed.

**Before (Line 473):**
```python
ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
```

**After (Fixed):**
```python
ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.OPEN, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
```

This now matches the status filter used in `_cancel_remaining_sl_tp()`, ensuring consistency across both cancellation methods.

## Changes Made

### 1. Fixed Status Filter in `_cancel_oco_sibling()`
- **File:** `backend/app/services/exchange_sync.py`
- **Line:** 473
- **Change:** Added `OrderStatusEnum.OPEN` to the status filter

### 2. Enhanced Diagnostic Logging

#### In `_cancel_oco_sibling()`:
- Added detailed logging when sibling orders are found but none are active
- Shows all sibling orders with their statuses to help diagnose issues

#### In `_cancel_remaining_sl_tp()`:
- Added comprehensive diagnostic logging when target orders are not found
- Logs executed order details (order_id, symbol, parent_order_id, order_role, order_type)
- Shows all target orders that exist but are in inactive statuses
- Includes parent_order_id and order_role for each order to help identify linkage issues

## Other Possible Reasons for Missing Cancellation

Even with the fix, there are other scenarios where TP orders might not be cancelled:

1. **Non-Active Status**: The TP order was already in a non-active status (CANCELLED, FILLED, REJECTED, EXPIRED) before the cancellation logic ran
2. **Missing OCO Linkage**: Orders don't share the same `oco_group_id`, or lack `parent_order_id`/`order_role` linkage
3. **Symbol Mismatch**: Orders have different symbols in the database
4. **Timing Issues**: Order execution wasn't detected properly, or the sync process hadn't run yet
5. **Multiple Fallback Strategies**: The cancellation uses multiple strategies (parent_order_id, order_role, time window, symbol+type), but if all fail, cancellation won't happen

## How to Diagnose Future Cases

With the enhanced logging, check the application logs for:

1. **OCO Cancellation Attempts:**
   - Look for: `"OCO: No active sibling found for {order_id} in group {oco_group_id}"`
   - This will show if siblings exist but are in inactive statuses

2. **Fallback Cancellation Attempts:**
   - Look for: `"No active {target_order_type} orders found to cancel for {symbol}"`
   - This will show:
     - Executed order details
     - All target orders that exist (with their statuses, parent_order_ids, and order_roles)
     - Which strategies were tried

## Testing Recommendations

1. **Test with OPEN Status Orders:**
   - Create SL/TP orders
   - Verify TP order is in OPEN status
   - Execute SL order
   - Verify TP order is cancelled

2. **Test Edge Cases:**
   - Orders without OCO group IDs
   - Orders without parent_order_id linkage
   - Orders with different symbols
   - Orders already in CANCELLED/FILLED status

## Files Modified

- `backend/app/services/exchange_sync.py`
  - Line 473: Added `OrderStatusEnum.OPEN` to status filter
  - Lines 477-489: Enhanced logging in `_cancel_oco_sibling()`
  - Lines 1402-1428: Enhanced logging in `_cancel_remaining_sl_tp()`

## Impact

- **Bug Fix**: TP orders in OPEN status will now be properly cancelled when SL orders execute
- **Improved Observability**: Better logging will help diagnose future issues more quickly
- **Consistency**: Both cancellation methods now use the same status filters



