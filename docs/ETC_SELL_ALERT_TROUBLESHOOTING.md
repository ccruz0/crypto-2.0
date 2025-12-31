# 🔍 Troubleshooting: ETC Not Creating Alerts and Sell Orders

## Problem
ETC (Ethereum Classic) is not creating alerts and sell orders when SELL signals are detected.

## Root Causes

Based on the codebase analysis, there are several potential reasons why ETC is not creating alerts and sell orders:

### 1. **Configuration Flags Not Enabled** (Most Common)

The system requires **multiple flags** to be enabled for SELL alerts and orders:

#### For SELL Alerts:
- ✅ `alert_enabled = True` (Master switch - REQUIRED)
- ✅ `sell_alert_enabled = True` (SELL-specific flag - REQUIRED)
- ✅ `sell_signal = True` (Signal from indicators - REQUIRED)

#### For SELL Orders (after alert):
- ✅ `trade_enabled = True` (REQUIRED for order creation)
- ✅ `trade_amount_usd > 0` (REQUIRED - must be configured)

**⚠️ IMPORTANT**: `sell_alert_enabled` defaults to `False` and must be explicitly enabled. This is separate from `alert_enabled`.

### 2. **Throttling Blocking Signals**

Even if flags are enabled, throttling can block alerts:

- **Time Gate**: Minimum 60 seconds between alerts for the same (symbol, side)
- **Price Gate**: Minimum price change % (from strategy) since last alert

### 3. **Missing Indicators**

SELL orders require:
- `MA50` must be available
- `EMA10` must be available

If these are missing, alerts are sent but orders are NOT created.

### 4. **Symbol Name Mismatch**

The system uses `ETC_USDT` (not `ETC_USD`). Verify the symbol in the watchlist matches exactly.

## Diagnostic Steps

### Step 1: Run Diagnostic Script

```bash
cd /Users/carloscruz/automated-trading-platform
python3 backend/scripts/check_etc_sell_alert.py
```

This script will check:
- Watchlist configuration
- Alert flags status
- Throttling state
- Strategy configuration
- Trade amount configuration

### Step 2: Check Database Configuration

Query the watchlist_items table:

```sql
SELECT 
    symbol,
    alert_enabled,
    sell_alert_enabled,
    buy_alert_enabled,
    trade_enabled,
    trade_amount_usd,
    strategy_id,
    sl_tp_mode
FROM watchlist_items
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;
```

### Step 3: Check Throttling State

```sql
SELECT 
    symbol,
    side,
    last_price as baseline_price,
    last_time as last_sent_at,
    force_next_signal as allow_immediate,
    emit_reason
FROM signal_throttle_states
WHERE symbol = 'ETC_USDT' AND side = 'SELL'
ORDER BY last_time DESC
LIMIT 1;
```

### Step 4: Check Backend Logs

Look for these log patterns:

```bash
# Check if SELL signals are detected
docker compose logs backend | grep -i "ETC.*SELL"

# Check for throttling blocks
docker compose logs backend | grep -i "ETC.*THROTTLED"

# Check for flag-related blocks
docker compose logs backend | grep -i "ETC.*sell_alert_enabled"
```

## Solutions

### Solution 1: Enable Required Flags (SQL)

If flags are disabled, run these SQL commands:

```sql
-- Enable master alert switch
UPDATE watchlist_items 
SET alert_enabled = TRUE 
WHERE symbol = 'ETC_USDT';

-- Enable SELL alerts specifically
UPDATE watchlist_items 
SET sell_alert_enabled = TRUE 
WHERE symbol = 'ETC_USDT';

-- Enable trading (for order creation)
UPDATE watchlist_items 
SET trade_enabled = TRUE 
WHERE symbol = 'ETC_USDT';

-- Set trade amount (if not configured)
UPDATE watchlist_items 
SET trade_amount_usd = 10.0 
WHERE symbol = 'ETC_USDT' 
AND (trade_amount_usd IS NULL OR trade_amount_usd <= 0);
```

### Solution 2: Enable via Dashboard

1. Go to the Dashboard
2. Find `ETC_USDT` in the watchlist
3. Enable:
   - ✅ **Alerts** toggle (master switch)
   - ✅ **SELL Alerts** toggle (SELL-specific)
   - ✅ **Trade** toggle (for orders)
   - ✅ Set **Amount USD** field (e.g., 10.0)

### Solution 3: Reset Throttling (if blocked)

If throttling is blocking, you can reset it:

```sql
-- Reset SELL throttling state for ETC_USDT
DELETE FROM signal_throttle_states
WHERE symbol = 'ETC_USDT' AND side = 'SELL';
```

**⚠️ WARNING**: This will allow immediate alerts but should only be done if you understand the implications.

### Solution 4: Check Signal Detection

Verify that SELL signals are actually being generated:

```bash
# Check current signals
curl http://localhost:8000/api/signals?exchange=CRYPTO_COM&symbol=ETC_USDT

# Look for "sell_signal": true in the response
```

## Verification Checklist

After applying fixes, verify:

- [ ] `alert_enabled = TRUE` in database
- [ ] `sell_alert_enabled = TRUE` in database
- [ ] `trade_enabled = TRUE` in database (for orders)
- [ ] `trade_amount_usd > 0` in database
- [ ] SELL signal is being detected (check logs/API)
- [ ] Throttling is not blocking (check `signal_throttle_states`)
- [ ] MA50 and EMA10 are available (check logs for missing indicators)

## Expected Behavior After Fix

Once configured correctly:

1. **SELL Signal Detected** → System checks flags
2. **Flags OK** → System checks throttling
3. **Throttling OK** → **SELL Alert Sent** ✅
4. **If `trade_enabled=True`** → **SELL Order Created** ✅

## Common Issues

### Issue: "Alert sent but order not created"

**Causes:**
- `trade_enabled = False`
- `trade_amount_usd` not configured or <= 0
- Missing MA50 or EMA10 indicators

**Solution:** Check logs for specific reason, then fix configuration.

### Issue: "No alert sent even with sell_signal=True"

**Causes:**
- `alert_enabled = False`
- `sell_alert_enabled = False`
- Throttling blocking (time gate or price gate)

**Solution:** Enable flags and/or wait for throttling to pass.

### Issue: "Throttling blocking immediately after enabling"

**Solution:** This is expected. After enabling flags, the first alert should be sent immediately (bypass). Subsequent alerts require throttling to pass.

## Related Documentation

- [ALERTAS_Y_ORDENES_NORMAS.md](./ALERTAS_Y_ORDENES_NORMAS.md) - Complete rules for alerts and orders
- `backend/app/services/signal_monitor.py` - Signal monitoring implementation
- `backend/app/services/signal_throttle.py` - Throttling logic

## Support

If issues persist after following this guide:

1. Run the diagnostic script: `backend/scripts/check_etc_sell_alert.py`
2. Check backend logs for specific error messages
3. Verify symbol name is exactly `ETC_USDT` (not `ETC_USD`)
4. Check that indicators (MA50, EMA10) are being calculated correctly











