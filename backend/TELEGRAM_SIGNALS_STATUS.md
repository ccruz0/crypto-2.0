# Telegram /signals Command - Current Status

## Issue
The `/signals` command shows "No signals generated yet" even though there are 20 signals in the TradeSignal table.

## Root Cause Analysis

### Current State
- **TradeSignal table**: 20 signals exist
- **MarketData table**: Has price, RSI, MA50, EMA10 for BTC, ETH, etc.
- **Watchlist**: BTC_USDT and ETH_USDT have alert_enabled=True, trade_enabled=True
- **Trading Scheduler**: Currently NOT running (showing False)

### The Problem
The `/signals` command filters for coins with `alert_enabled==True` OR `trade_enabled==True`, which should return BTC and ETH signals. However, it's showing "No signals generated yet".

Possible causes:
1. Trading Scheduler not running → Telegram commands not processing
2. Database connection issue in Telegram command handler
3. Query logic error in the filter
4. Data mismatch between tables

## Changes Made

### Improvements to `/signals` Command

1. **Added MarketData Integration**
   - Now queries MarketData table for technical indicators
   - Fallback chain: Signal → MarketData → Watchlist → API

2. **Enhanced Display**
   - Signal Price (historical)
   - Current Price (from MarketData or API)
   - Percentage change with color (🟢/🔴)
   - Technical parameters (RSI, MA50, EMA10, Volume)
   - Order information or reason if not placed

3. **Price Sources**
   - Primary: MarketData table (updated by market-updater)
   - Backup: Crypto.com API (/public/get-tickers)
   - Fallback: Signal's historical price

## Data Verification

### MarketData Table (Confirmed Working)
```
BTC_USDT:
  price: $101,528.32 ✓
  rsi: 41.25 ✓
  ma50: $102,573.08 ✓
```

### TradeSignal Table (Needs Verification)
```
BTC_USDT:
  current_price: None (needs population)
  rsi: None (needs population)
  ma50: None (needs population)
```

## Next Steps

1. **Enable Trading Scheduler**
   - Required for Telegram commands to process
   - Currently disabled by `DEBUG_DISABLE_TRADING_SCHEDULER`

2. **Populate TradeSignal Data**
   - Run `sync_watchlist_to_signals(db)` to copy data
   - Or update `upsert_trade_signal` to pull from MarketData

3. **Test Query Locally**
   - Verify the filter logic works
   - Ensure signals are returned for BTC/ETH

4. **Monitor Logs**
   - Check for "[TG][CMD] /signals" in logs
   - Verify query executes without errors

## Temporary Workaround

The `/signals` command has been updated to:
- Query MarketData for all technical data
- Fetch prices from API if database is empty
- Show comprehensive signal information

However, the Trading Scheduler must be running for Telegram commands to work.

## Status
⏸️ Partially implemented - waiting for Trading Scheduler to process commands

