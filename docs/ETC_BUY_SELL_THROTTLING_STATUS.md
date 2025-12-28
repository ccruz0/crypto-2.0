# ✅ ETC_USDT Throttling Status - BUY & SELL

## Configuration Change Reset - Both Sides

When you change watchlist parameters, the system automatically resets throttling for **both BUY and SELL** sides independently.

## Current Status (2025-12-25)

### BUY Side
- **Throttling State**: ✅ **EXISTS**
- **force_next_signal**: ✅ **True**
- **Last Price**: None
- **Last Time**: 1970-01-01 (reset timestamp)
- **Status**: ✅ **UNBLOCKED** - Next BUY alert will bypass throttling

### SELL Side
- **Throttling State**: ✅ **CLEARED** (no record)
- **Status**: ✅ **UNBLOCKED** - First SELL alert allowed immediately

## Expected Behavior

### BUY Alerts/Orders
1. **BUY Signal Detected** → Flags checked ✅
2. **Throttling Check** → `force_next_signal=True` → **BYPASS** ✅
3. **Alert Sent Immediately** ✅
4. **Order Created** (if `trade_enabled=True` and `trade_amount_usd` set) ✅

### SELL Alerts/Orders
1. **SELL Signal Detected** → Flags checked ✅
2. **Throttling Check** → No state → **ALLOWED** ✅
3. **Alert Sent Immediately** ✅
4. **Order Created** (if `trade_enabled=True` and `trade_amount_usd` set) ✅

## How Configuration Change Reset Works

When watchlist parameters change (strategy, flags, etc.):

1. **Reset Throttle State**: Resets baseline price and timestamp
2. **Set force_next_signal**: Sets `force_next_signal = True` for **both BUY and SELL**
3. **Clear Order Limitations**: Clears order creation locks

This ensures immediate alerts/orders after configuration changes.

## After First Alert

After the first alert is sent:
- `force_next_signal` is cleared to `False`
- Normal throttling applies:
  - Time gate: 60 seconds minimum
  - Price gate: 1% minimum price change (from strategy)

## Independent Sides

**BUY and SELL are completely independent:**
- Each side has its own throttling state
- Resetting one side doesn't affect the other
- Configuration changes reset **both sides** simultaneously
- Each side can be unblocked independently

## Summary

✅ **BUY**: Unblocked (`force_next_signal=True`)  
✅ **SELL**: Unblocked (no throttling state)

Both sides are ready to trigger alerts and orders immediately when signals are detected!

---

**Date**: 2025-12-25  
**Symbol**: ETC_USDT  
**Status**: Both BUY and SELL unblocked ✅









