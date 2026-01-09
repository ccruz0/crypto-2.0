# Investigation: Last Buy Signal Alert Analysis

## 📊 Alert Details

**Symbol:** TRX_USDT  
**Timestamp:** 2026-01-09 03:10:59 UTC  
**Alert ID:** 140676

## 🔍 Root Cause Analysis

### Primary Reason: THROTTLED_PRICE_GATE

**Decision Type:** SKIPPED  
**Reason Code:** `THROTTLED_DUPLICATE_ALERT`  
**Reason Message:** "Alert blocked for TRX_USDT BUY: THROTTLED_PRICE_GATE (absolute price change ↓ 0.05% < 1.00%)"

### Context Data

```json
{
  "price": 0.2941541372061668,
  "symbol": "TRX_USDT",
  "strategy_key": "swing:conservative",
  "reference_price": 0.2942920722197843,
  "throttle_reason": "THROTTLED_PRICE_GATE (absolute price change ↓ 0.05% < 1.00%)",
  "reference_timestamp": "2026-01-08T18:04:09.634403+00:00"
}
```

### Price Analysis

- **Current Price:** $0.29415
- **Reference Price (last alert):** $0.29429
- **Price Change:** -0.05% (decreased)
- **Required Change:** 1.00%
- **Time Since Last Alert:** ~9 hours (18:04:09 → 03:10:59)

## 🚫 Why No Order Was Created

### 1. Alert Throttling (Blocked Before Order Creation)

The alert was **blocked at the throttle check stage**, which happens **BEFORE**:
- Sending to Telegram
- Attempting order creation
- Any order evaluation logic

**Throttle Mechanism:**
- **Time Gate:** ✅ Passed (9 hours > 60 seconds required)
- **Price Gate:** ❌ **FAILED** (0.05% < 1.00% required)

### 2. Throttle Configuration

The system requires a **minimum 1.00% price change** between alerts to prevent duplicate notifications when price hasn't moved significantly.

**Configuration:**
- `min_price_change_pct`: 1.00%
- `min_interval_minutes`: 1 minute (60 seconds)

### 3. Watchlist Configuration

**TRX_USDT Settings:**
- ✅ `trade_enabled`: `true`
- ✅ `alert_enabled`: `true`
- ✅ `buy_alert_enabled`: `true`
- ✅ `trade_amount_usd`: $10
- ✅ `trade_on_margin`: `true`

**All settings are correct** - the symbol is fully configured for trading.

## 📈 What Would Have Happened If Alert Passed?

If the price had moved ≥1.00%, the flow would have been:

1. ✅ **Alert sent to Telegram** (BUY signal notification)
2. ✅ **Order creation attempted** (via `_create_buy_order()`)
3. **Order creation checks:**
   - ✅ Trade enabled check
   - ✅ Trade amount configured
   - ✅ Balance check (if SPOT)
   - ✅ Max open orders check
   - ✅ Recent orders cooldown
   - ✅ Trading guardrails
   - ✅ Order placement attempt

## 🎯 Key Insights

### 1. Throttling is Working as Designed

The throttle system **correctly prevented** a duplicate alert when:
- Price only moved 0.05% (essentially unchanged)
- Last alert was sent 9 hours ago
- Price is very close to previous alert price ($0.29415 vs $0.29429)

### 2. Decision Tracing is Working

✅ The system correctly:
- Detected the throttle block
- Recorded it with `SKIPPED` decision type
- Stored reason code `THROTTLED_DUPLICATE_ALERT`
- Included context JSON with price details
- Saved to database for Monitor UI display

### 3. No Order Creation Attempted

This is **expected behavior** - when an alert is throttled:
- No Telegram message is sent
- No order creation is attempted
- The alert is blocked early in the pipeline

## 🔧 Recommendations

### Option 1: Accept Current Behavior (Recommended)

The throttle is working correctly. A 0.05% price change is essentially noise, and blocking duplicate alerts prevents spam.

**Action:** None required - system is functioning as designed.

### Option 2: Adjust Throttle Threshold (If Needed)

If you want more frequent alerts, you could:

1. **Reduce `min_price_change_pct`** from 1.00% to 0.50% or lower
2. **Location:** Configured in throttle settings (check `signal_throttle.py` or config)

**Trade-off:** More alerts = more notifications, but also more potential for duplicate alerts on small price movements.

### Option 3: Manual Override (For Testing)

If you want to test order creation for TRX_USDT:

1. Wait for price to move ≥1.00% from $0.29429
2. Or manually trigger by adjusting throttle state in database
3. Or temporarily reduce `min_price_change_pct` threshold

## 📋 Summary

| Aspect | Status | Details |
|--------|--------|---------|
| **Alert Detected** | ✅ Yes | BUY signal was detected |
| **Throttle Check** | ❌ Failed | Price change 0.05% < 1.00% required |
| **Telegram Sent** | ❌ No | Blocked before sending |
| **Order Attempted** | ❌ No | Blocked before order creation |
| **Decision Traced** | ✅ Yes | Recorded as SKIPPED with reason |
| **Configuration** | ✅ Valid | All watchlist settings correct |

## ✅ Conclusion

**The system is working correctly.** The alert was blocked by the throttle mechanism because the price hadn't moved enough (0.05% vs 1.00% required). This is expected behavior to prevent duplicate alerts on insignificant price movements.

**No order was created because:**
1. The alert never passed the throttle check
2. Order creation only happens after a successful alert send
3. The throttle correctly identified this as a duplicate scenario

**Decision tracing captured this correctly** with:
- Decision Type: SKIPPED
- Reason Code: THROTTLED_DUPLICATE_ALERT
- Full context with price details

---

**Investigation Date:** 2026-01-09  
**Status:** ✅ System functioning as designed  
**Action Required:** None (unless you want to adjust throttle threshold)

