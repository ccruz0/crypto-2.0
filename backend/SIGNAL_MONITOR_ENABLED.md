# Signal Monitor Service - Enabled

## Status
✅ Signal Monitor Service **ENABLED** and running

## Configuration

**File:** `backend/app/main.py`
```python
DEBUG_DISABLE_SIGNAL_MONITOR = False  # Enabled - creates orders ONLY for trade_enabled=True coins
```

## How It Works

### Monitoring
- **Interval:** Every 30 seconds
- **Filter:** Monitors coins with `alert_enabled = True`
- **Actions:** Sends alerts + creates orders (if conditions met)

### Order Creation Logic

```
FOR each coin with alert_enabled=True:
  
  IF BUY signal detected:
    1. Send Telegram alert (ALWAYS)
    
    2. IF trade_enabled=True AND trade_amount_usd > 0:
         Create order automatically in crypto.com ✅
       ELSE:
         Alert only, no order ❌
  
  IF SELL signal detected:
    1. Send Telegram alert (ALWAYS)
    2. NO order creation (SELL signals are alerts only)
```

## Current Configuration

### Coins with Alert=YES
1. **BTC_USDT**
   - alert_enabled: ✅ YES
   - trade_enabled: ✅ YES
   - trade_amount_usd: $100
   - **Result:** Alerts + Automatic Orders

2. **ETH_USDT**
   - alert_enabled: ✅ YES
   - trade_enabled: ✅ YES
   - trade_amount_usd: $10
   - **Result:** Alerts + Automatic Orders

3. **BONK_USDT** (example)
   - alert_enabled: ✅ YES
   - trade_enabled: ❌ NO
   - **Result:** Alerts ONLY (no orders)

## What Will Happen

Every 30 seconds, the Signal Monitor will:

1. Check BTC_USDT, ETH_USDT, BONK_USDT (all have alert_enabled=True)

2. If BUY signal detected:
   - **BTC/ETH**: Alert + Create order (trade_enabled=True)
   - **BONK**: Alert only (trade_enabled=False)

3. If SELL signal detected:
   - All: Alert only (no automatic orders for SELL)

## Logs to Watch

```bash
docker logs automated-trading-platform-backend-1 -f | grep signal_monitor
```

Expected logs:
```
Signal monitoring service started
🟢 NEW BUY signal detected for BTC_USDT
✅ Trade enabled for BTC_USDT - creating BUY order automatically
✅ Automatic BUY order created successfully: BTC_USDT - ORDER_ID
```

Or if trade_enabled=False:
```
🟢 NEW BUY signal detected for BONK_USDT
ℹ️ Alert sent for BONK_USDT but trade_enabled = false - no order created
```

## Safety Features

1. **Duplicate Prevention**: Tracks processed orders to avoid creating duplicates
2. **Amount Validation**: Requires `trade_amount_usd > 0`
3. **Trade Flag**: Only creates orders if `trade_enabled = True`
4. **Error Handling**: Continues monitoring even if one coin fails
5. **Telegram Notifications**: Sends errors if order creation fails

## To Disable

If you want to disable automatic order creation:

```python
DEBUG_DISABLE_SIGNAL_MONITOR = True
```

Then restart backend:
```bash
docker compose --profile local restart backend
```

## Current Status

✅ **ENABLED** - Signal Monitor is actively monitoring and will create orders for BTC_USDT and ETH_USDT when signals are detected (trade_enabled=True)

⏸️ **ALERT ONLY** for coins with trade_enabled=False (they get alerts but no orders)

---

**Enabled:** November 7, 2025, 10:35  
**Next check:** Within 30 seconds  
**Mode:** Automatic orders ONLY for Trade=YES coins

