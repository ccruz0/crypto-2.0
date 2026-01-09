# FIL_USDT SELL Order Test Status

## Current Status

**Throttle State:** ✅ Cleared (ready for next alert)  
**RSI:** 62.8 (below SELL threshold ~70+)  
**Next Alert:** Waiting for RSI to reach SELL threshold  

## Configuration

**Watchlist Items (FIL_USDT):**
- Row 1: `trade_enabled=true`, `trade_amount_usd=10`, `trade_on_margin=true`, `sell_alert_enabled=true`, `alert_enabled=true` ✅
- Row 2: `trade_enabled=false`, `trade_on_margin=false`, `sell_alert_enabled=false`, `alert_enabled=false` ❌

**Note:** Duplicate rows - code should use enabled one

## Fixes Deployed

1. ✅ **Error 306 Retry Logic for SELL Orders** (Commit 75ffbfa)
   - Leverage reduction retry (5x → 3x → 1x)
   - SPOT fallback (checks base currency balance)
   - Decision tracing for all failure scenarios

2. ✅ **Early Balance Check** (Already implemented)
   - Skips balance check for margin orders (line 3828)
   - Only checks balance for SPOT orders

## Expected Behavior

When next FIL_USDT SELL signal triggers (RSI >= 70):
1. ✅ Alert sent to Telegram
2. ✅ Order creation attempted with margin enabled
3. ✅ If error 306 occurs:
   - Retry with reduced leverage (5x → 3x → 1x)
   - If that fails, try SPOT fallback (if FIL balance available)
   - Emit decision tracing with full context
4. ✅ Monitor UI shows decision details

## Monitoring

**Current RSI:** 62.8  
**SELL Threshold:** ~70+  
**Status:** Waiting for RSI to reach SELL threshold

**Recent Alerts:** None (RSI below threshold)

## Next Steps

1. Wait for FIL_USDT RSI to reach SELL threshold (~70+)
2. Monitor logs for order creation attempt
3. Verify error 306 retry logic works (if error occurs)
4. Check Monitor UI for decision tracing (if order blocked/failed)

---

**Status:** ✅ Ready for testing  
**Date:** 2026-01-09  
**Waiting for:** RSI >= 70 for SELL signal

