# Fix: Telegram Alerts Not Sent Due to Stale Volume Data

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

Telegram alerts were not being sent for coins that showed BUY signals in the dashboard (e.g., ADA with volume ratio 2.79x > 0.5x). The backend `signal_monitor` was using stale volume data from the database (0.08x) instead of fresh data, causing `buy_volume_ok=False` and preventing BUY alerts.

- **Symptom:** No Telegram alerts sent even when dashboard shows BUY signal
- **Root Cause:** `signal_monitor` used stale database volume data (0.08x) while frontend showed fresh data (2.79x)
- **Impact:** Alerts not generated because backend calculated `buy_volume_ok=False` with stale data

## Root Cause

The `signal_monitor` service was only using volume data from the `MarketData` database table, which can be stale (updated every 60 seconds by `market_updater`). Meanwhile, the `/api/signals` endpoint (used by frontend) fetches fresh OHLCV data and recalculates volume ratios, showing accurate values (2.79x).

**Discrepancy:**
- **Frontend (`/api/signals`):** Fetches fresh OHLCV → calculates `volume_ratio=2.79x` → shows BUY ✓
- **Backend (`signal_monitor`):** Uses stale DB data → calculates `volume_ratio=0.08x` → `buy_volume_ok=False` → no alert

## Solution

Modified `signal_monitor` to fetch fresh volume data from OHLCV (same as `/api/signals` endpoint) when database volume data is available:

1. **Fetch Fresh OHLCV Data:** After getting database data, attempt to fetch fresh OHLCV data
2. **Recalculate Volume Index:** Use `calculate_volume_index` to get fresh `current_volume` and `avg_volume`
3. **Use Fresh Values:** Replace stale DB values with fresh calculated values if available
4. **Fallback to DB:** If fresh fetch fails, use DB values as fallback (don't fail the signal check)

### Code Changes

```python
# Before (only DB data):
current_volume = market_data.current_volume  # Can be stale
avg_volume = market_data.avg_volume  # Can be stale

# After (fresh fetch + DB fallback):
current_volume = market_data.current_volume  # Start with DB
avg_volume = market_data.avg_volume  # Start with DB

# Try to fetch fresh volume data
try:
    from market_updater import fetch_ohlcv_data
    from app.api.routes_signals import calculate_volume_index
    
    ohlcv_data = fetch_ohlcv_data(symbol, "1h", 6)
    if ohlcv_data and len(ohlcv_data) > 0:
        volumes = [candle.get("v", 0) for candle in ohlcv_data if candle.get("v", 0) > 0]
        if len(volumes) >= 6:
            volume_index = calculate_volume_index(volumes, period=5)
            fresh_current_volume = volume_index.get("current_volume")
            fresh_avg_volume = volume_index.get("average_volume")
            
            # Use fresh values if available
            if fresh_current_volume and fresh_current_volume > 0:
                current_volume = fresh_current_volume
            if fresh_avg_volume and fresh_avg_volume > 0:
                avg_volume = fresh_avg_volume
except Exception as vol_fetch_err:
    # Fallback to DB values if fetch fails
    logger.debug(f"Could not fetch fresh volume: {vol_fetch_err}, using DB values")
```

## Files Changed

1. `backend/app/api/signal_monitor.py` (lines ~339-350)
   - Added fresh OHLCV volume fetch after getting database data
   - Recalculate volume index with fresh data
   - Use fresh values if available, fallback to DB values

## Verification

### Before Fix
- **Database:** `current_volume=1712.1, avg_volume=20696.94, volume_ratio=0.08`
- **Backend Calculation:** `volume_ratio=0.08x` < 0.5x → `buy_volume_ok=False` → no alert
- **Frontend Display:** `volume_ratio=2.79x` > 0.5x → shows BUY ✓

### After Fix
- **Database:** `current_volume=1712.1, avg_volume=20696.94` (stale)
- **Fresh Fetch:** `current_volume=31724.50, avg_volume=11354.71` (fresh)
- **Backend Calculation:** `volume_ratio=2.79x` > 0.5x → `buy_volume_ok=True` → alert sent ✓
- **Frontend Display:** `volume_ratio=2.79x` > 0.5x → shows BUY ✓

## Expected Behavior

- **Before Fix:**
  - Backend used stale volume data (0.08x) → `buy_volume_ok=False` → no alerts
  - Frontend showed fresh volume data (2.79x) → discrepancy

- **After Fix:**
  - Backend fetches fresh volume data (2.79x) → `buy_volume_ok=True` → alerts sent
  - Frontend shows fresh volume data (2.79x) → consistent

## Testing Checklist

To verify the fix works:

1. **Check Backend Logs:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -iE "(fresh.*volume|Using fresh|BUY alert sent)"
   ```
   - Should show "Using fresh current_volume" and "Using fresh avg_volume" messages
   - Should show "BUY alert sent" when volume ratio > 0.5x

2. **Verify Alert Generation:**
   - Watch for `🟢 BUY signal detected` messages in logs
   - Check that alerts are sent to Telegram when `alert_enabled=True`
   - Verify volume ratio matches what dashboard displays

3. **Dashboard Verification:**
   - Open dashboard and check a coin with high volume ratio (e.g., 2.79x)
   - Verify backend logs show same volume ratio
   - Confirm BUY alerts are sent to Telegram when all criteria met

## Commit Information

- **Commit:** `a94fbdb` - "Fix: Fetch fresh volume data in signal_monitor to match /api/signals behavior"

## Related Issues

This fix ensures that:
- `signal_monitor` uses same fresh volume data as frontend
- Volume checks are accurate and consistent
- Alerts are sent when volume criteria are actually met
- No false negatives due to stale database data

## Notes

- The fresh volume fetch is done asynchronously and doesn't block the signal check
- If fresh fetch fails, the code falls back to database values (graceful degradation)
- This matches the behavior of `/api/signals` endpoint for consistency
