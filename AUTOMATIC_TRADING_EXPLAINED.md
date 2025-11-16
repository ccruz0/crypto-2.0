# Automatic Trading - Why Orders Were Executed

## What Happened

Your orders were executed because **automatic trading is enabled** for SOL_USDT in your watchlist.

### Order Breakdown:

1. **BUY MARKET @ $167.46** (Order ID: 5755600477886670468)
   - Created automatically by Signal Monitor Service when BUY signal detected
   - Executed immediately (MARKET order)

2. **SELL LIMIT @ $162.00** (Order ID: 5755600477885583539)
   - Likely a **STOP_LOSS** order created automatically when BUY order was filled
   - This protects your position from losses

3. **BUY MARKET @ $166.98** (Order ID: 5755600477885552283)
   - Another automatic BUY order created when signal changed
   - Executed immediately (MARKET order)

## How Automatic Trading Works

The **Signal Monitor Service** runs every 30 seconds and:

1. Checks all coins with `alert_enabled = true` in your watchlist
2. Calculates trading signals (BUY/SELL/WAIT) based on:
   - RSI (Relative Strength Index)
   - Moving Averages (MA50, EMA10)
   - Price action
3. **Automatically creates BUY orders** when:
   - `alert_enabled = true` ✅
   - `trade_enabled = true` ✅
   - `trade_amount_usd` is configured ✅
   - BUY signal is detected ✅
   - Maximum 3 open orders per symbol (not exceeded)
   - Price changed at least 3% from last order (for subsequent orders)

4. **Automatically creates SL/TP orders** when:
   - A BUY order is filled
   - Uses watchlist configuration (sl_percentage, tp_percentage, sl_tp_mode)

## How to Control Automatic Trading

### Option 1: Disable Trading for Specific Coin (Keep Alerts)

In the Dashboard Watchlist:
- Set **"Trade"** to **NO** (or `trade_enabled = false`)
- Keep **"Alert"** as **YES** (or `alert_enabled = true`)
- Result: You'll get Telegram alerts but NO automatic orders

### Option 2: Disable All Alerts for Coin

In the Dashboard Watchlist:
- Set **"Alert"** to **NO** (or `alert_enabled = false`)
- Result: No alerts, no orders

### Option 3: Stop Signal Monitor Service Entirely

The Signal Monitor Service can be stopped via:
- API endpoint: `POST /api/control/stop` (stops signal_monitor)
- Or modify `backend/app/main.py` to disable it on startup

### Option 4: Use DRY RUN Mode

Set environment variable:
```bash
LIVE_TRADING=false
```

This will simulate orders but not execute real trades.

## Current Configuration Check

To check if automatic trading is enabled for SOL_USDT:

1. **Check Dashboard**: Go to Watchlist → SOL_USDT
   - Look for "Trade" column - should be YES/NO
   - Look for "Alert" column - should be YES/NO
   - Look for "Amount USD" - should have a value

2. **Check Logs**: Look for messages like:
   ```
   ✅ Trade enabled for SOL_USDT - creating BUY order automatically
   ```

3. **Check API**: 
   ```bash
   GET /api/dashboard/state
   ```
   Look for `trade_enabled: true` for SOL_USDT

## Important Notes

- **SELL signals** only send alerts - they do NOT create automatic orders
- **BUY signals** create MARKET orders automatically (if trade_enabled = true)
- **SL/TP orders** are created automatically when BUY orders fill
- The service checks every 30 seconds
- Maximum 3 open orders per symbol
- Requires 3% price change to create additional orders

## If You Want to Disable Automatic Trading

1. **Quick Fix**: In Dashboard, set "Trade" to NO for SOL_USDT
2. **Permanent Fix**: Set `trade_enabled = false` for all coins you don't want to auto-trade
3. **Service Level**: Stop the signal_monitor service via API or code

## Questions?

- Check logs: `backend/logs/` directory
- Check Telegram notifications for order creation messages
- Review `backend/app/services/signal_monitor.py` for full logic

