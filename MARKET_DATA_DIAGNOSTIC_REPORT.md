# Market Data Diagnostic Report

**Generated:** 2025-12-03

## Summary

✅ **Fix Applied:** Values now display instead of "-" (enrichment logic fixed)

⚠️ **Current Issue:** Most items showing default values instead of calculated ones:
- **87.9%** of items have RSI=50 (default value)
- **100%** of items have Volume=NULL in watchlist items

## Findings

### 1. RSI Values
- **Status:** 29/33 items (87.9%) showing default RSI=50.0
- **Cause:** Market updater is not successfully calculating real RSI values
- **Root Cause:** Insufficient OHLCV data (< 50 candles) or fetch failures

### 2. Volume Values
- **Status:** 100% of watchlist items showing Volume=NULL
- **Finding:** Volume data EXISTS in `/api/signals` endpoint (volume_ratio=0.037...)
- **Issue:** Volume fields not being enriched from MarketData to watchlist items
- **Missing Fields:** `volume_ratio`, `current_volume`, `avg_volume` not included in enrichment

### 3. Price & MA Values
- ✅ Prices are present and updating
- ✅ MA50, MA200, EMA10 are present (using current_price as fallback when no historical data)

## Root Causes

### Primary Issue: Market Updater Not Calculating Real RSI

The market-updater-aws process needs to:
1. Fetch OHLCV data (200 candles from Binance/Crypto.com)
2. Calculate RSI from at least 15+ price points (ideally 50+)
3. Save calculated values to MarketData table

**When RSI defaults to 50.0:**
- Code path: `backend/market_updater.py:217` - returns default when `< 50 candles`
- Code path: `backend/app/api/routes_signals.py:21` - returns default when `< period + 1` (15 candles)

### Secondary Issue: Volume Fields Not Enriched

The enrichment code in `routes_dashboard.py` doesn't include volume fields:
- Missing: `volume_ratio`, `current_volume`, `avg_volume`
- These exist in MarketData model but aren't transferred to watchlist items

## Next Steps

### Immediate Actions Required on AWS:

1. **Check if market-updater-aws is running:**
   ```bash
   docker-compose --profile aws ps | grep market-updater
   ```

2. **Check market-updater-aws logs:**
   ```bash
   docker-compose --profile aws logs market-updater-aws --tail=100
   ```

3. **Look for these log patterns:**
   - ✅ `"✅ Indicators for {symbol}: RSI=..."` - Real calculations working
   - ✅ `"✅ Fetched {N} candles from Binance"` - OHLCV fetch successful
   - ⚠️ `"⚠️ No OHLCV data"` - Fetch failures
   - ⚠️ `"Error calculating indicators"` - Calculation errors

4. **Verify MarketData table freshness:**
   - Check `updated_at` timestamps should be < 2 minutes old
   - If stale, market updater may not be running

### Code Fixes Needed:

1. **Add volume fields to enrichment** (if volume data should be shown in dashboard):
   - Add `volume_ratio`, `current_volume`, `avg_volume` to `_serialize_watchlist_item` enrichment

2. **Investigate why OHLCV fetches are failing** (if logs show failures):
   - Check API rate limits
   - Check network connectivity
   - Check Binance/Crypto.com API status

## Diagnostic Script

Run this script locally to check current status:
```bash
python3 check_market_data_via_api.py
```

## Expected Behavior

Once market-updater-aws is working correctly:
- RSI values should vary (typically 30-70 range, not stuck at 50)
- Volume values should show actual ratios (e.g., 1.2x, 0.8x, not 0 or NULL)
- Values should update every 60-90 seconds

## Files Modified

1. ✅ `backend/app/api/routes_dashboard.py` - Fixed enrichment to always prefer MarketData
2. ✅ `frontend/src/app/api.ts` - Added missing TypeScript interface fields
3. ⚠️ TODO: Add volume fields to enrichment if needed for dashboard display

Generated: 2025-12-20 17:22:17



