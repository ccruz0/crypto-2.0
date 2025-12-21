# AAVE Position Counting Bug

## Problem

The system is incorrectly counting 7 "open positions" for AAVE when the user doesn't actually have 7 open positions.

### Current Behavior

The position counting logic in `order_position_service.py` counts **individual filled BUY orders** that haven't been fully offset by SELL orders, rather than counting actual open positions.

**From logs:**
```
filled_buy=29.232 AAVE
filled_sell=23.469 AAVE  
net_qty=5.763 AAVE
final_positions=7  ← This is wrong!
```

### Root Cause

The counting logic uses FIFO matching to determine which BUY orders are "open":
1. It iterates through all filled BUY orders
2. For each BUY order, if it hasn't been fully offset by SELL orders, it counts as 1 position
3. If you have 7 small BUY orders and only partial SELL orders, it counts all 7 as "open positions"

**The problem:** This counts historical filled orders as positions, even when they should be consolidated or the actual position count is lower.

### Code Location

`backend/app/services/order_position_service.py` lines 137-156:

```python
for buy_order in filled_buy_orders:
    buy_qty = _order_filled_quantity(buy_order)
    if buy_qty <= 0:
        continue

    if remaining_sell_qty >= buy_qty:
        # This BUY is fully closed by earlier SELLs
        remaining_sell_qty -= buy_qty
    else:
        # This BUY still has some net quantity open -> count as one open position
        open_filled_positions += 1  # ← This counts each order separately
        remaining_sell_qty = 0.0
```

### Impact

- Test orders are blocked when they shouldn't be
- The system thinks there are 7 positions when there might only be 1-2 actual positions
- Users can't create new orders even when they have room

## Solution Options

### Option 1: Count Based on Net Quantity (Recommended)

Instead of counting individual orders, count based on net quantity divided by average position size:

```python
# Calculate average position size from filled orders
if len(filled_buy_orders) > 0:
    avg_position_size = filled_buy_qty / len(filled_buy_orders)
    estimated_positions = max(1, int(round(net_quantity / avg_position_size)))
else:
    estimated_positions = 0
```

### Option 2: Use Exchange API for Actual Positions

Query the exchange API directly for actual open positions instead of counting historical orders:

```python
# Get actual positions from exchange
actual_positions = trade_client.get_positions()
aave_positions = [p for p in actual_positions if p['symbol'].startswith('AAVE')]
```

### Option 3: Fix FIFO Logic

Improve the FIFO matching to properly consolidate positions:

```python
# Instead of counting each order, count consolidated positions
# Group orders that are effectively the same position
```

## Temporary Workaround

To allow test orders to proceed, you can:

1. **Manually adjust the limit check** - Modify `_should_block_open_orders` to be less strict
2. **Clear old order history** - Remove old filled orders that are skewing the count
3. **Use exchange API positions** - Query actual positions from Crypto.com instead of counting historical orders

## Verification

To verify the actual number of open positions:

1. Check the Dashboard's "Open Orders" tab
2. Query the exchange API directly: `trade_client.get_positions()`
3. Check account balance for AAVE holdings

The discrepancy between what the system counts (7) and what actually exists suggests the counting logic needs to be fixed.







