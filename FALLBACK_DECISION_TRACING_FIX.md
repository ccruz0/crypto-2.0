# Fallback Decision Tracing Fix

## Problem

When alerts were sent but orders were not created, the original alert messages didn't have decision tracing. The fallback mechanism existed but wasn't executing because it was in the wrong code block.

## Root Cause

The `else` clause with fallback decision tracing (line 3628) was inside the `if watchlist_item.trade_enabled:` block (line 3411), not at the same level as `if should_create_order:` (line 2971).

**Flow:**
1. `should_create_order=False` is set (line 2932) due to `blocked_by_limits`
2. Code reaches `if should_create_order:` (line 2971)
3. Since `should_create_order=False`, the `if` block is skipped
4. The `else` at line 3628 is never reached because it's inside `if watchlist_item.trade_enabled:`, which is inside `if should_create_order:`

## Fix

Changed the `else` to an `if not should_create_order:` check at the same indentation level as `if should_create_order:`. This ensures the fallback executes when `should_create_order=False`.

**Before:**
```python
if should_create_order:
    # ... order creation logic ...
    if watchlist_item.trade_enabled:
        # ... trade enabled logic ...
    else:
        # ... trade disabled logic ...
        # Note: This else was at wrong level
else:
    # Fallback decision tracing - NEVER REACHED!
```

**After:**
```python
if should_create_order:
    # ... order creation logic ...
    if watchlist_item.trade_enabled:
        # ... trade enabled logic ...
    else:
        # ... trade disabled logic ...

# Handle case when should_create_order=False (at correct level)
if not should_create_order:
    # Fallback decision tracing - NOW EXECUTES!
```

## Expected Behavior

When an alert is sent but `should_create_order=False`:
1. ✅ Alert sent to Telegram
2. ✅ `should_create_order=False` is set (due to guard clauses)
3. ✅ Fallback decision tracing executes (NEW)
4. ✅ TRADE_BLOCKED event emitted with decision tracing
5. ✅ Monitor UI shows decision details

## Testing

To verify the fix:
1. Trigger an alert for a symbol
2. Ensure `should_create_order=False` (e.g., due to MAX_OPEN_ORDERS or COOLDOWN)
3. Verify fallback decision tracing is emitted
4. Check Monitor UI shows decision details

---

**Status:** ✅ Fixed  
**Date:** 2026-01-09  
**Commit:** To be created
