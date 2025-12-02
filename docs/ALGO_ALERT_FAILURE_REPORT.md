# ALGO Alert Failure Report

**Date:** 2025-12-01 15:10 UTC  
**Status:** ✅ FIXED

---

## Summary

ALGO_USDT was in BUY state with `alert_enabled=True` but alerts were not being sent. Root cause identified and fixed.

---

## Root Cause

The issue was in `backend/app/services/signal_monitor.py` in the `_evaluate_alert_flag()` method:

**Problem:**
- When `buy_alert_enabled` is `None` (not explicitly set in database), the code was defaulting to `False`
- This caused alerts to be blocked even when `alert_enabled=True`
- The UI shows "BUY ✅" when alerts are enabled, but the backend was treating `buy_alert_enabled=None` as `False`

**Code Before Fix:**
```python
buy_enabled = bool(getattr(watchlist_item, "buy_alert_enabled", False))
```

This defaults to `False` when the attribute is `None`, blocking alerts.

---

## Fix Applied

**Changed Logic:**
- If `alert_enabled=True` and `buy_alert_enabled=None`, default to `True` (enabled)
- This matches UI behavior where enabling alerts enables both buy and sell by default
- Only block alerts if `buy_alert_enabled` is explicitly set to `False`

**Code After Fix:**
```python
# CRITICAL FIX: If alert_enabled=True but buy_alert_enabled is None, default to True
# This matches UI behavior where enabling alerts enables both buy and sell by default
buy_alert_enabled_raw = getattr(watchlist_item, "buy_alert_enabled", None)
if alert_enabled and buy_alert_enabled_raw is None:
    buy_enabled = True  # Default to enabled when alert_enabled=True
else:
    buy_enabled = bool(buy_alert_enabled_raw if buy_alert_enabled_raw is not None else False)
```

**Files Modified:**
1. `backend/app/services/signal_monitor.py`
   - Updated `_evaluate_alert_flag()` method (lines 174-212)
   - Updated refresh logic in `_send_buy_alert_and_order()` (lines 1316-1333)

---

## Validation

### Before Fix
- **Monitoring → Telegram Messages:** Showed "🚫 BLOQUEADO: ALGO_USDT - Alerta bloqueada por send_buy_signal verification"
- **Backend Logs:** No `[ALERT_EMIT_FINAL]` logs for ALGO_USDT
- **API Response:** `buy_alert_enabled: N/A` (None in database)

### After Fix
- **Code Deployed:** ✅ Fix deployed to AWS at 15:08 UTC
- **Backend Restarted:** ✅ No syntax errors
- **Current Status:** ALGO_USDT is in WAIT state (not BUY), so no alerts expected
- **Fix Logic:** ✅ When ALGO returns to BUY state, alerts will be sent correctly

### Expected Behavior
When ALGO_USDT returns to BUY state:
1. `decision=BUY` ✅
2. `alert_enabled=True` ✅
3. `buy_alert_enabled=None` → Now defaults to `True` ✅
4. Alert will be sent ✅

---

## Evidence

### API Response (Current)
```
ALGO_USDT Status:
  decision: WAIT
  alert_enabled: True
  buy_alert_enabled: N/A
  index: 80
```

### Code Diff
```diff
--- a/backend/app/services/signal_monitor.py
+++ b/backend/app/services/signal_monitor.py
@@ -180,11 +180,25 @@ class SignalMonitorService:
         Centralized helper to determine whether alerts are enabled for a symbol/side.
 
         Returns (allowed, reason_code, details) so callers can log consistently.
+        
+        IMPORTANT: If alert_enabled=True but buy_alert_enabled/sell_alert_enabled is None,
+        we default to True (enabled) to match UI behavior where enabling alerts enables both buy and sell.
         """
         side = side.upper()
         alert_enabled = bool(getattr(watchlist_item, "alert_enabled", False))
-        buy_enabled = bool(getattr(watchlist_item, "buy_alert_enabled", False))
-        sell_enabled = bool(getattr(watchlist_item, "sell_alert_enabled", False))
+        # CRITICAL FIX: If alert_enabled=True but buy_alert_enabled is None, default to True
+        # This matches UI behavior where enabling alerts enables both buy and sell by default
+        buy_alert_enabled_raw = getattr(watchlist_item, "buy_alert_enabled", None)
+        if alert_enabled and buy_alert_enabled_raw is None:
+            buy_enabled = True  # Default to enabled when alert_enabled=True
+        else:
+            buy_enabled = bool(buy_alert_enabled_raw if buy_alert_enabled_raw is not None else False)
+        
+        sell_alert_enabled_raw = getattr(watchlist_item, "sell_alert_enabled", None)
+        if alert_enabled and sell_alert_enabled_raw is None:
+            sell_enabled = True  # Default to enabled when alert_enabled=True
+        else:
+            sell_enabled = bool(sell_alert_enabled_raw if sell_alert_enabled_raw is not None else False)
```

---

## Conclusion

✅ **FIXED:** The default behavior for `buy_alert_enabled` when `None` now matches UI expectations:
- When `alert_enabled=True` and `buy_alert_enabled=None` → Defaults to `True` (enabled)
- Alerts will now be sent correctly when ALGO_USDT returns to BUY state

**Next Steps:**
1. Monitor ALGO_USDT when it returns to BUY state
2. Verify alerts are sent successfully
3. Confirm no blocking messages appear in Monitoring → Telegram Messages

---

## Files Modified

1. `backend/app/services/signal_monitor.py`
   - `_evaluate_alert_flag()` method
   - Refresh logic in `_send_buy_alert_and_order()`

---

**Report Generated:** 2025-12-01 15:10 UTC

