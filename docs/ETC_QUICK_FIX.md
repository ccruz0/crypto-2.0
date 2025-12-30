# 🚀 Quick Fix: ETC Not Creating Alerts and Sell Orders

## Quick Diagnosis

### Option 1: Check via API (Fastest - No Docker needed if backend is running)

```bash
cd /Users/carloscruz/automated-trading-platform
./backend/scripts/check_etc_via_api.sh
```

This will check the current configuration via the API endpoint.

### Option 2: Run Diagnostic Script (Requires Database Access)

```bash
cd /Users/carloscruz/automated-trading-platform
python3 backend/scripts/check_etc_sell_alert.py
```

This will:
- Check all configuration flags
- Verify throttling state
- Identify specific issues
- Provide SQL fix commands

## Quick Fix

### Option 1: Run Fix Script (Recommended)

```bash
cd /Users/carloscruz/automated-trading-platform
python3 backend/scripts/fix_etc_sell_alerts.py
```

This script will automatically:
- ✅ Enable `alert_enabled`
- ✅ Enable `sell_alert_enabled`
- ✅ Enable `trade_enabled` (for orders)
- ✅ Set `trade_amount_usd` to $10 if not configured

### Option 2: Fix via SQL (Direct Database Access)

```sql
-- Enable all required flags
UPDATE watchlist_items 
SET 
    alert_enabled = TRUE,
    sell_alert_enabled = TRUE,
    trade_enabled = TRUE,
    trade_amount_usd = COALESCE(NULLIF(trade_amount_usd, 0), 10.0)
WHERE symbol = 'ETC_USDT' AND is_deleted = FALSE;
```

### Option 3: Fix via Dashboard UI

1. Go to Dashboard
2. Find `ETC_USDT` in the watchlist
3. Enable:
   - ✅ **Alerts** toggle (master switch)
   - ✅ **SELL Alerts** toggle (SELL-specific)
   - ✅ **Trade** toggle (for orders)
   - ✅ Set **Amount USD** field (e.g., 10.0)

## Verify Fix

After applying the fix, verify it worked:

```bash
# Check via API
./backend/scripts/check_etc_via_api.sh

# Or check database directly
# (if you have database access)
```

## Common Issues After Fix

### Issue: "Still not creating alerts"

**Possible causes:**
1. **Throttling blocking** - Wait 60 seconds or reset throttling:
   ```sql
   DELETE FROM signal_throttle_states 
   WHERE symbol = 'ETC_USDT' AND side = 'SELL';
   ```

2. **No SELL signal detected** - Check if indicators show SELL conditions:
   ```bash
   curl "http://localhost:8000/api/signals?exchange=CRYPTO_COM&symbol=ETC_USDT"
   ```
   Look for `"sell_signal": true` in response

3. **Missing indicators** - Check logs for "MA50" or "EMA10" missing

### Issue: "Alerts sent but orders not created"

**Check:**
- `trade_enabled = TRUE` ✅
- `trade_amount_usd > 0` ✅
- MA50 and EMA10 are available (check logs)

## Expected Behavior

Once fixed, the system will:

1. **Detect SELL Signal** (RSI > 70, etc.)
2. **Check Flags** (`alert_enabled` + `sell_alert_enabled`)
3. **Check Throttling** (60s cooldown + price change %)
4. **Send SELL Alert** ✅
5. **Create SELL Order** ✅ (if `trade_enabled=True`)

## Files Created

- `backend/scripts/check_etc_sell_alert.py` - Full diagnostic
- `backend/scripts/fix_etc_sell_alerts.py` - Automatic fix
- `backend/scripts/check_etc_via_api.sh` - Quick API check
- `docs/ETC_SELL_ALERT_TROUBLESHOOTING.md` - Detailed guide

## Need More Help?

See the detailed troubleshooting guide:
- `docs/ETC_SELL_ALERT_TROUBLESHOOTING.md`










