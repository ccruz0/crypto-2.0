# BTC_USD Sell Alert Analysis

## Current Situation

According to the dashboard image:
- ✅ **SELL signal is being generated** (shown in dashboard)
- ✅ **All criteria met**: RSI 91.26 > 70, MA50 < EMA10 (0.74% diff), Volume 1.21x >= 0.5x
- ✅ **Backend confirms**: "Señal: SELL (todos los criterios SELL cumplidos según backend)"

**But alerts are NOT being sent to Telegram.**

## BTC_USD Strategy Configuration

From `trading_config.json`:
```json
"BTC_USD": {
  "preset": "scalp-conservative"
}
```

**Strategy: Scalp-Conservative**

### Sell Conditions for Scalp-Conservative:
1. ✅ **RSI > 70** (BTC_USD: 91.26 ✅ **MET**)
2. ✅ **MA reversal NOT REQUIRED** (Scalp has `ma50: false` in maChecks)
3. ✅ **Volume >= 0.5x** (BTC_USD: 1.21x ✅ **MET**)
4. ✅ **`sell_alert_enabled=True`** ✅ (just enabled for all symbols)
5. ✅ **`alert_enabled=True`** ✅ (should be enabled)

## Why Alerts Aren't Being Sent

Since the signal is being generated but alerts aren't sent, the issue is likely:

### 1. **Throttle Blocking** (Most Likely)
- Recent SELL alert already sent for BTC_USD
- Cooldown period not expired
- Price change insufficient (< 1.0% for Scalp-Conservative)

### 2. **Signal Monitor Service Not Running**
- The `SignalMonitorService` might not be active
- Check backend logs for signal monitor activity

### 3. **Telegram Notifier Issue**
- `send_sell_signal()` might be failing silently
- Check backend logs for Telegram errors

### 4. **Flag Check Failing**
- `sell_alert_enabled` might still be False for BTC_USD specifically
- Need to verify database value

## Diagnostic Steps

### Step 1: Check if sell_alert_enabled is True for BTC_USD
```sql
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled 
FROM watchlist_items 
WHERE symbol = 'BTC_USD';
```

### Step 2: Check Backend Logs
Look for these patterns:
```
🔍 BTC_USD SELL alert decision: sell_signal=True, ...
✅ SELL alert SENT for BTC_USD
⏭️  SELL alert BLOCKED for BTC_USD (throttling)
```

### Step 3: Check Throttle Status
Check if a recent SELL alert was sent for BTC_USD that's causing throttling.

### Step 4: Verify Signal Monitor is Running
Check if the signal monitor service is active and processing BTC_USD.

## Quick Fix

If `sell_alert_enabled` is False for BTC_USD specifically:

```sql
UPDATE watchlist_items 
SET sell_alert_enabled = TRUE 
WHERE symbol = 'BTC_USD' 
  AND alert_enabled = TRUE;
```

Or run the enable script again to ensure BTC_USD is included.

## Expected Behavior

Once all conditions are met:
1. Signal monitor detects SELL signal ✅ (already happening)
2. Checks `sell_alert_enabled=True` ✅ (should be enabled)
3. Checks throttle status ❓ (likely blocking)
4. Sends Telegram alert via `send_sell_signal()` ❓ (might be failing)

The most likely issue is **throttling** - a recent SELL alert was already sent, and the cooldown/price change requirements haven't been met yet.




