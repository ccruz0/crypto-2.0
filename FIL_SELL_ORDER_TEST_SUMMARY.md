# FIL_USDT SELL Order Test Summary

## Previous Failure (Before Fix)

**Order ID:** 140731  
**Timestamp:** 2026-01-09 04:27:40  
**Status:** ❌ AUTOMATIC SELL ORDER CREATION FAILED  
**Error:** 500 Server Error: INSUFFICIENT_AVAILABLE_BALANCE (code: 306)  
**Issue:** ❌ No decision tracing recorded (this was before the fix)

This order failed with error 306 because:
- Margin SELL order was attempted
- Exchange returned error 306 (insufficient margin available)
- No retry logic was in place (before fix)
- No decision tracing was recorded (before fix)

## Fixes Applied

### 1. Error 306 Retry Logic for SELL Orders ✅
**Commit:** 75ffbfa

**What it does:**
- Detects error 306 when margin SELL order fails
- Retries with reduced leverage (5x → 3x → 1x)
- Falls back to SPOT if all leverage retries fail (if base currency balance available)
- Emits decision tracing with full context

### 2. Decision Tracing for SELL Order Failures ✅
**Commit:** 75ffbfa

**What it does:**
- Records decision_type (FAILED)
- Records reason_code (INSUFFICIENT_FUNDS or EXCHANGE_REJECTED)
- Records reason_message with full context
- Records exchange_error_snippet with raw error
- Records correlation_id for log tracing

## Current Status

**Throttle State:** ✅ Cleared  
**RSI:** 62.8 (below SELL threshold ~70+)  
**Next SELL Signal:** Waiting for RSI >= 70  

## Configuration

**FIL_USDT Watchlist:**
- ✅ `trade_enabled=true`
- ✅ `trade_amount_usd=10`
- ✅ `trade_on_margin=true` (margin enabled)
- ✅ `sell_alert_enabled=true`
- ✅ `alert_enabled=true`

**Note:** There are duplicate rows - one enabled, one disabled. Code should use the enabled one.

## Expected Behavior (Next SELL Signal)

When FIL_USDT RSI reaches SELL threshold (~70+):

1. **Alert Sent** ✅
   - Telegram notification with SELL signal
   - RSI, price, indicators, etc.

2. **Order Creation Attempted** ✅
   - With margin enabled (as configured)
   - Amount: $10.00
   - Margin trading active

3. **If Error 306 Occurs** (Expected behavior after fix):
   - ✅ System detects error 306
   - ✅ Tries with reduced leverage (5x → 3x → 1x)
   - ✅ If that fails, tries SPOT fallback (checks FIL balance)
   - ✅ Emits decision tracing with full context:
     - `decision_type`: FAILED
     - `reason_code`: INSUFFICIENT_FUNDS or EXCHANGE_REJECTED
     - `reason_message`: Detailed explanation
     - `exchange_error_snippet`: Raw error message
     - `context_json`: Full context (leverage attempts, fallback attempts, etc.)
   - ✅ Monitor UI shows blocked entry with decision details
   - ✅ Telegram notification with failure details

4. **If Order Succeeds**:
   - ✅ ORDER_CREATED event
   - ✅ Order placed on exchange
   - ✅ SL/TP orders created after fill

## Monitoring Commands

**Check for new alerts:**
```bash
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "SELECT id, symbol, LEFT(message, 100) as msg_preview, blocked, decision_type, reason_code, timestamp FROM telegram_messages WHERE symbol = 'FIL_USDT' AND timestamp >= NOW() - INTERVAL '10 minutes' ORDER BY timestamp DESC LIMIT 10;"
```

**Check logs for order attempts:**
```bash
docker compose --profile aws logs --tail 500 market-updater-aws 2>&1 | grep -i 'FIL_USDT.*SELL\|FIL_USDT.*order\|FIL_USDT.*306\|FIL_USDT.*retry\|FIL_USDT.*leverage'
```

**Check current RSI:**
```bash
docker compose --profile aws logs --tail 100 market-updater-aws 2>&1 | grep -i 'FIL_USDT.*RSI'
```

## Next Steps

1. ✅ Wait for FIL_USDT RSI to reach SELL threshold (~70+)
2. ✅ Monitor for SELL signal alert
3. ✅ Monitor for order creation attempt
4. ✅ Verify error 306 retry logic works (if error occurs)
5. ✅ Verify decision tracing is recorded (if order fails)
6. ✅ Check Monitor UI for decision details

---

**Status:** ✅ Ready for testing  
**Fixes:** ✅ Deployed  
**Date:** 2026-01-09  
**Waiting for:** RSI >= 70 for next SELL signal

