# Entry Price Implementation

## Problem
The user wanted to see the **historical price** when a signal was created vs the **current price**, to track performance with a percentage change indicator.

Previously, `TradeSignal.current_price` was being updated on every sync, overwriting the original price. This made it impossible to calculate the actual performance of signals.

## Solution

### Database Changes

Added new field to `TradeSignal` model:

```python
entry_price = Column(Float, nullable=True)  # Price when signal was CREATED (never updated)
current_price = Column(Float, nullable=True)  # Current/latest price (updated regularly)
```

### Logic Changes

**In `upsert_trade_signal()`:**

1. **When CREATING a new signal:**
   ```python
   entry_price = entry_price or current_price  # Set to creation price
   current_price = current_price  # Also set current
   ```

2. **When UPDATING an existing signal:**
   ```python
   if entry_price and not existing.entry_price:
       existing.entry_price = entry_price  # Only set if not already set
   existing.current_price = current_price  # Always update
   ```

### Display in `/signals` Command

```
💰 Signal Price: $98,500.00  ← entry_price (never changes)
💵 Current Price: $101,613.22 ← current_price (updates regularly)
   Change: +3.16% 🟢
```

## Migration of Existing Data

For existing signals that don't have `entry_price`:
- Set `entry_price = current MarketData.price`
- This gives them a baseline for future comparisons
- Not historically accurate, but provides a starting point

## Future Behavior

### When a New Signal is Created
1. `entry_price` = price at creation time
2. `current_price` = same price initially
3. On updates: `entry_price` stays fixed, `current_price` updates

### After Some Time
```
Time 0 (Creation):
  entry_price = $100
  current_price = $100
  Change: 0%

Time +1 hour:
  entry_price = $100  (unchanged)
  current_price = $102 (updated)
  Change: +2.00% 🟢

Time +2 hours:
  entry_price = $100  (unchanged)
  current_price = $98  (updated)
  Change: -2.00% 🔴
```

## Benefits

1. **Track Performance**: See if signal is in profit or loss
2. **Historical Context**: Know the price when decision was made
3. **Decision Validation**: Evaluate if signals are accurate
4. **Portfolio Tracking**: Understand P&L on pending signals

## Files Modified

- `backend/app/models/trade_signal.py`: Added `entry_price` field
- `backend/app/services/signal_writer.py`: Updated `upsert_trade_signal()` to handle `entry_price`
- `backend/app/services/telegram_commands.py`: Updated `send_signals_message()` to use `entry_price`

## Testing

After implementation:
1. Create a new signal for a coin
2. Wait for price to change
3. Run `/signals` in Telegram
4. Should see different values for Signal Price vs Current Price

## Status

✅ Database schema updated with `entry_price` field  
✅ Logic updated to preserve entry price  
✅ `/signals` command uses entry_price for historical comparison  
⏳ Existing signals migrated with current price as baseline  
⏳ New signals will capture true entry price

