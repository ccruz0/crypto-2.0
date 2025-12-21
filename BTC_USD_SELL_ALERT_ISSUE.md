# BTC_USD Sell Alert Issue - Analysis & Solution

## Current Situation

According to the dashboard:
- ✅ **SELL signal IS being generated** (shown in dashboard with "SELL" tag)
- ✅ **All criteria met**: 
  - RSI 91.26 > 70 ✅
  - MA50 < EMA10 (0.74% difference) ✅
  - Volume 1.21x >= 0.5x ✅
- ✅ **Backend confirms**: "Señal: SELL (todos los criterios SELL cumplidos según backend)"

**But Telegram alerts are NOT being sent.**

## BTC_USD Strategy

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

## Why Alerts Aren't Being Sent

Since the signal is generated but alerts aren't sent, check these in order:

### 1. **sell_alert_enabled Flag** (Check First)

The enable script should have set this, but verify:

```sql
SELECT symbol, alert_enabled, buy_alert_enabled, sell_alert_enabled 
FROM watchlist_items 
WHERE symbol = 'BTC_USD';
```

**If `sell_alert_enabled = FALSE`:**
```sql
UPDATE watchlist_items 
SET sell_alert_enabled = TRUE 
WHERE symbol = 'BTC_USD' 
  AND alert_enabled = TRUE;
```

### 2. **Throttle Blocking** (Most Likely)

Check if a recent SELL alert was already sent:

**Check backend logs for:**
```
🔍 BTC_USD SELL alert decision: sell_signal=True, ...
⏭️  SELL alert BLOCKED for BTC_USD (throttling): ...
```

**Throttle reasons:**
- Recent alert sent (cooldown not expired)
- Price change < 1.0% (for Scalp-Conservative: `minPriceChangePct: 1.0`)

**Solution:** Wait for cooldown or price to change by 1%+

### 3. **Signal Monitor Service Not Running**

Check if the signal monitor is active:

**Check backend logs for:**
```
🚀 SIGNAL MONITORING SERVICE STARTED
```

**If not running:** Restart the backend service

### 4. **Telegram Notifier Issue**

Check if `send_sell_signal()` is failing:

**Check backend logs for:**
```
❌ Failed to send SELL alert for BTC_USD
[TELEGRAM_ERROR] symbol=BTC_USD side=SELL
```

## Quick Diagnostic Commands

### Check Configuration (via SSM):
```bash
# Run this on AWS server
docker exec -it $(docker ps -q -f name=backend | head -1) python3 << 'PYEOF'
import sys
sys.path.insert(0, '/app')
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
db = SessionLocal()
item = db.query(WatchlistItem).filter(WatchlistItem.symbol == 'BTC_USD').first()
if item:
    print(f"Symbol: {item.symbol}")
    print(f"alert_enabled: {item.alert_enabled}")
    print(f"sell_alert_enabled: {getattr(item, 'sell_alert_enabled', False)}")
    print(f"buy_alert_enabled: {getattr(item, 'buy_alert_enabled', False)}")
else:
    print("BTC_USD NOT FOUND")
db.close()
PYEOF
```

### Check Recent Logs:
```bash
# On AWS server
docker logs $(docker ps -q -f name=backend | head -1) 2>&1 | grep -i "BTC_USD.*SELL" | tail -20
```

## Most Likely Issue

Based on the dashboard showing the signal is generated but alerts aren't sent:

**Most likely: Throttle blocking**

The signal monitor likely:
1. Detected the SELL signal ✅
2. Checked `sell_alert_enabled` ✅ (should be True now)
3. Checked throttle status ❓ **→ BLOCKED** (recent alert or insufficient price change)
4. Skipped sending alert

**Check the throttle status in the Monitoring tab** - it should show if a recent SELL alert was sent for BTC_USD.

## Solution

1. **Verify `sell_alert_enabled=True`** for BTC_USD (run SQL check above)
2. **Check throttle status** in Monitoring tab
3. **Check backend logs** for throttle reasons
4. **Wait for cooldown** or **price change** if throttled

The signal generation is working correctly - the issue is in the alert sending step (throttle or flag check).




