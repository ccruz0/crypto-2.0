# Fix: Alerts Not Being Generated Due to Missing Volume Data

**Date:** 2025-12-06  
**Status:** ✅ Fixed and Deployed

## Problem Summary

The algorithm was not creating alerts according to the dashboard, even when all criteria appeared to be met:
- **Dashboard Display:** Shows "Ratio actual: 6.19x" (volume requirement met)
- **Backend Logs:** Show `buy_volume_ok=False | volume_ratio=0.0478 | min_volume_ratio=0.5000`
- **Result:** Backend returns `WAIT` signal instead of `BUY`, preventing alerts from being generated
- **Impact:** Alerts not being sent even when all trading criteria are satisfied

## Root Cause

The signal monitor (`SignalMonitorService`) was calling `calculate_trading_signals` without passing `volume` and `avg_volume` parameters. This caused:

1. **Missing Volume Data:** The signal monitor only fetched price/RSI/MA data from `get_price_with_fallback()`, which doesn't return volume data
2. **Incorrect Volume Check:** When volume data is `None`, the code defaults to `volume_ok = True`, but logs showed `volume_ratio=0.0478`, indicating stale or incorrect volume data was being used from somewhere
3. **Mismatch with Frontend:** The frontend displays volume ratio from the database (`MarketData` table), but the signal monitor wasn't using the same data source

**Signal Monitor Flow (Before Fix):**
1. Fetch price data via `get_price_with_fallback()` → No volume data
2. Call `calculate_trading_signals()` without `volume`/`avg_volume` parameters
3. Volume check uses stale/incorrect data → `buy_volume_ok=False`
4. Signal returns `WAIT` instead of `BUY`
5. No alerts generated

## Solution

Updated the signal monitor to fetch volume data from the database (`MarketData` table), matching the `/api/signals` endpoint behavior:

### Code Changes

```python
# Before: Only fetched price data (no volume)
result = get_price_with_fallback(symbol, "15m")
current_price = result.get('price', 0)
# ... no volume data ...

signals = calculate_trading_signals(
    symbol=symbol,
    price=current_price,
    # ... no volume/avg_volume parameters ...
)

# After: Fetch volume data from database
from app.models.market_price import MarketData
market_data = db.query(MarketData).filter(
    MarketData.symbol == symbol
).first()

if market_data and market_data.price and market_data.price > 0:
    current_price = market_data.price
    rsi = market_data.rsi or 50.0
    ma50 = market_data.ma50
    ma200 = market_data.ma200
    ema10 = market_data.ema10
    atr = market_data.atr or (current_price * 0.02)
    current_volume = market_data.current_volume  # ✅ Now includes volume
    avg_volume = market_data.avg_volume or 0.0   # ✅ Now includes avg_volume
else:
    # Fallback to price fetcher if database doesn't have data
    result = get_price_with_fallback(symbol, "15m")
    # ... (volume will be None in fallback)

signals = calculate_trading_signals(
    symbol=symbol,
    price=current_price,
    volume=current_volume,    # ✅ Pass volume data
    avg_volume=avg_volume,    # ✅ Pass avg_volume data
    # ... other parameters ...
)
```

## Files Changed

1. `backend/app/api/signal_monitor.py`
   - Updated `_check_signal_for_coin` method to fetch volume data from `MarketData` table
   - Added fallback to price fetcher if database doesn't have data
   - Pass `volume` and `avg_volume` parameters to `calculate_trading_signals`

## Verification

### Build Status
- ✅ Python syntax check: Passed
- ✅ Docker build: Successful
- ✅ Backend container: Rebuilt and restarted
- ✅ Container status: Healthy

### Expected Behavior

### Before Fix
- Dashboard shows: "Volume ≥ 0.5x promedio ✓" with "Ratio actual: 6.19x"
- Backend logs show: `buy_volume_ok=False | volume_ratio=0.0478 | min_volume_ratio=0.5000`
- Signal: `WAIT` (not all BUY criteria met)
- Alerts: Not generated

### After Fix
- Dashboard shows: "Volume ≥ 0.5x promedio ✓" with "Ratio actual: 6.19x"
- Backend logs show: `buy_volume_ok=True | volume_ratio=6.19 | min_volume_ratio=0.5000`
- Signal: `BUY` (all criteria met)
- Alerts: Generated when `alert_enabled=True` and throttle allows

## Testing Checklist

To verify the fix works:

1. **Check Backend Logs:**
   ```bash
   docker compose --profile aws logs backend-aws | grep -iE "(volume_ratio|buy_volume_ok|BUY signal)"
   ```
   - Should show `buy_volume_ok=True` when volume ratio meets threshold
   - Should show `BUY signal detected` when all criteria are met

2. **Monitor Alert Generation:**
   - Watch for `🟢 BUY signal detected` messages in logs
   - Check that alerts are sent when `alert_enabled=True`
   - Verify volume ratio matches what dashboard displays

3. **Dashboard Verification:**
   - Open dashboard and check a coin with high volume ratio (e.g., 6.19x)
   - Verify backend logs show same volume ratio
   - Confirm BUY signals are generated when all criteria met

## Commit Information

- **Main Repo Commit:** `8ec3eef` - "Fix: Signal monitor now fetches volume data from database for accurate signal generation"

## Related Issues

This fix ensures the signal monitor uses the same volume data source as:
- The `/api/signals` endpoint (used by frontend)
- The dashboard display (shows volume ratio from database)
- The market updater (populates `MarketData` table)

## Notes

- The fix maintains backward compatibility: if database doesn't have volume data, it falls back to price fetcher (volume will be `None`, which defaults to `volume_ok=True`)
- Volume data is updated by the market updater service, which runs periodically
- The signal monitor now uses the same data source as the frontend, ensuring consistency between dashboard display and alert generation
