# Fix: BONK Duplicate Entries in Telegram Status

## Problem

BONK_USDT (and potentially other symbols) appeared multiple times in the Telegram status message:
- Multiple entries in "Trade Amounts" section
- Multiple entries in "Auto Trading" section

**Example:**
```
BONK_USDT: $10.00
BONK_USDT: $10,000.00
BONK_USDT: $10.00
```

## Root Cause

The `send_status_message()` function was iterating through all `WatchlistItem` records with `trade_enabled=True` without deduplicating by symbol. If multiple database entries existed for the same symbol (e.g., BONK_USDT), all of them were added to the lists.

## Solution

**File:** `backend/app/services/telegram_commands.py`  
**Function:** `send_status_message()`

### Changes Made

1. **Added Deduplication Logic:**
   - Use dictionaries (`auto_trading_dict`, `trade_amounts_dict`) to track unique symbols
   - Only add first occurrence of each symbol (most recent entry based on `created_at`)

2. **Sorting:**
   - Sort coins by `created_at` descending to keep most recent entry
   - Handle `None` created_at values with default datetime

3. **Final Output:**
   - Convert dictionaries to sorted lists (alphabetically by symbol)
   - Ensures consistent ordering and no duplicates

### Code Changes

**Before:**
```python
for coin in active_trade_coins:
    symbol = coin.symbol or "N/A"
    margin = "✅" if coin.trade_on_margin else "❌"
    auto_trading_coins.append(f"{symbol} (Margin: {margin})")
    
    amount = coin.trade_amount_usd or 0
    if amount > 0:
        trade_amounts_list.append(f"{symbol}: ${amount:,.2f}")
    else:
        trade_amounts_list.append(f"{symbol}: N/A")
```

**After:**
```python
# Use dictionaries to deduplicate by symbol (keep most recent entry)
auto_trading_dict = {}
trade_amounts_dict = {}

# Sort by created_at descending to keep most recent entry for each symbol
sorted_coins = sorted(
    active_trade_coins, 
    key=lambda c: c.created_at if c.created_at else min_datetime, 
    reverse=True
)

for coin in sorted_coins:
    symbol = coin.symbol or "N/A"
    
    # Only add if we haven't seen this symbol before (deduplication)
    if symbol not in auto_trading_dict:
        margin = "✅" if coin.trade_on_margin else "❌"
        auto_trading_dict[symbol] = f"{symbol} (Margin: {margin})"
    
    # Only add trade amount if we haven't seen this symbol before
    if symbol not in trade_amounts_dict:
        amount = coin.trade_amount_usd or 0
        if amount > 0:
            trade_amounts_dict[symbol] = f"{symbol}: ${amount:,.2f}"
        else:
            trade_amounts_dict[symbol] = f"{symbol}: N/A"

# Convert dictionaries to lists (sorted by symbol for consistency)
auto_trading_coins = [auto_trading_dict[s] for s in sorted(auto_trading_dict.keys())]
trade_amounts_list = [trade_amounts_dict[s] for s in sorted(trade_amounts_dict.keys())]
```

## Result

- ✅ Each symbol appears only once in Trade Amounts list
- ✅ Each symbol appears only once in Auto Trading list
- ✅ Most recent entry is kept when duplicates exist
- ✅ Lists are sorted alphabetically for consistency

## Deployment

**Commit:** `4957fc8` - "fix: Deduplicate symbols in Telegram status message"  
**Status:** Deployed to AWS  
**Date:** 2025-12-22

## Testing

After deployment, verify:
1. Send `/status` command in Telegram
2. Check that each symbol appears only once
3. Verify BONK_USDT appears only once with correct amount
4. Verify all other symbols are also deduplicated

